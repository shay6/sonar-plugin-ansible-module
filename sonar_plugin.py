#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2018, Shay Shevach <shshevac@redhat.com>

# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import, division, print_function

__metaclass__ = type
from ansible.module_utils.basic import AnsibleModule
import requests
from requests.auth import HTTPBasicAuth
import os
import urllib
from distutils.version import LooseVersion
import re
import urllib2
from HTMLParser import HTMLParser

ANSIBLE_METADATA = {
    'metadata_version': '1.0',
    'supported_by': 'community',
    'status': ['preview']
}

DOCUMENTATION = '''
---
module: sonar_plugin
description: |
    Manage plugins installation in a sonarqube server as well as removal or
    update.
short_description: Manage plugins in SonarQube server.
euthor: "Shay Shevach"
options:
    name:
        description: |
            Plugin name as it is represented by Sonar.
    state:
        description: |
            Whether to install or remove a plugin. You can also choose "latest".
    version:
        description: |
            The specific version of the plugin.
    custom_url:
        description: |
            The plugin download URL, instead of using sonar api.
    hostname:
        description: |
            SonarQube hostname. default="localhost".
    username:
        description: |
            SonarQube user that has admin privileges. default="admin".
    password:
        description: |
            Password of the above user. default="admin".
    pending_dir:
        description: |
            The plugins pending folder. It puts the plugins in it into
            pending status. default = "/usr/local/sonar/extensions/downloads/".
    sonar_port:
        description: |
            Sonar UI port. default="9000".
'''

EXAMPLES = '''
- name: Install "3D Code Metrics" plugin using the api
    sonar_plugin:
      name: 3D Code Metrics
      state: installed

- name: Remove "C++ (Community)" plugin using the api
    sonar_plugin:
      name: C++ (Community)
      state: removed

- name: Update "Git" plugin using the api
    sonar_plugin:
      name: Git
      state: latest

- name: Install custom plugin from GitHub
    sonar_plugin:
      custom_url: https://github.com/shakedlokits/ruby-sonar-plugin/releases/download/v2.0.0/sonar-ruby-plugin-2.0.0.jar

- name: Update an existing plugin to a specific version, using URL
    sonar_plugin:
      custom_url: https://binaries.sonarsource.com/Distribution/sonar-java-plugin/sonar-java-plugin-5.9.2.16552.jar

- name: Install a specific version from "binaries.sonarsource.com"
    sonar_plugin:
      name: JaCoCo
      state: installed
      version: 1.0.1.143

- name: Update to a specific version from "binaries.sonarsource.com"
    sonar_plugin:
      name: SonarJava
      state: installed
      version: 5.9.2.16552

- name: Downgrade to a specific version from "binaries.sonarsource.com"
    sonar_plugin:
      name: SonarJava
      state: installed
      version: 5.8.0.15699
'''

RETURN = ''' # '''


class LinksParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.recording = 0
        self.data = []

    def handle_starttag(self, tag, attributes):
        if tag != 'a':
            return
        if self.recording:
            self.recording += 1
            return
        self.recording = 1

    def handle_endtag(self, tag):
        if tag == 'a' and self.recording:
            self.recording -= 1

    def handle_data(self, data):
        if self.recording:
            self.data.append(data)


def apply_post_api(sonar_url, api, module, plugin_data, status):
    url = sonar_url + api
    requests.post(url, data=plugin_data,
                  auth=HTTPBasicAuth(module.params['username'],
                                     module.params['password']))

    msg = switch_msg(status)

    if is_plugin_pending(plugin_data['key'], status, module):
        module.exit_json(changed=True, stdout=msg)


def switch_msg(status):
    return {
        'installing': 'SUCCESS: The plugin is installed',
        'removing': 'SUCCESS: The plugin was removed',
        'updating': 'SUCCESS: The plugin latest version is installed',
    }[status]


def get_key_by_name(sonar_url, api, module):
    key = 'not-found'
    url = sonar_url + api
    response = requests.get(url, auth=HTTPBasicAuth(module.params['username'],
                                                    module.params['password']))
    json_obj = response.json()

    for plugin in json_obj['plugins']:
        if plugin['name'] == module.params['name']:
            key = plugin['key']

    return key


def is_plugin_pending(key, status, module):
    is_pending = False
    pending_api = '/api/plugins/pending'
    cancel_all_api = '/api/plugins/cancel_all'
    hostname = module.params['hostname']
    port = module.params['sonar_port']

    url = 'http://' + hostname + ':' + str(port) + pending_api
    response = requests.get(url, auth=HTTPBasicAuth(module.params['username'],
                                                    module.params['password']))
    json_obj = response.json()

    if "errors" in json_obj:
        cancel_url = 'http://' + hostname + ':' + str(port) + cancel_all_api
        requests.post(cancel_url, auth=HTTPBasicAuth(module.params['username'],
                                                     module.params['password']))
        module.exit_json(changed=False,
            stdout='FAILED: This plugin is broken or not exist in repo. The operation '
                'canceled and all plugins was removed from pending list')

    if status == 'custom':
        for stat in json_obj:
            if stat != 'removing':
                for curr_stat in json_obj[stat]:
                    if curr_stat['key'] == key:
                        is_pending = True
    else:
        for stat in json_obj[status]:
            if stat['key'] == key:
                is_pending = True

    return is_pending


def download_custom_plugin(plugin_url, download_folder, status):
    filename = os.path.basename(plugin_url)

    filename_path = download_folder + filename
    urllib.urlretrieve(plugin_url, filename_path)

    if status == 'custom':
        key = 'not-found'
        match = re.search('sonar-(.*)-plugin', filename)
        if match is not None:
            key = match.group(1)
            final_key = re.sub('-', '', key)
            return final_key


def is_plugin_installed(module, sonar_url, installed_list_api):
    is_installed = False
    url = sonar_url + installed_list_api
    response = requests.get(url, auth=HTTPBasicAuth(module.params['username'],
                                                    module.params['password']))
    json_obj = response.json()
    for plugin in json_obj['plugins']:
        if plugin['name'] == module.params['name']:
            is_installed = True

    return is_installed


def is_plugin_installation_available(module, sonar_url, available_list_api):
    is_available = False
    url = sonar_url + available_list_api

    response = requests.get(url, auth=HTTPBasicAuth(module.params['username'],
                                                    module.params['password']))
    json_obj = response.json()

    for plugin in json_obj['plugins']:
        if plugin['name'] == module.params['name']:
            if not plugin['update']['requires'] and plugin['update']['status'] == 'COMPATIBLE':
                is_available = True
                version_available = plugin['release']['version']
                if module.params['version']:
                    comparison = compare_plugins_version(module.params['version'], version_available)
                    if comparison == 'Bigger':
                        is_available = False

    return is_available


def compare_plugins_version(plugin_version, version_available):
    output = 'Equal'
    comparable_version = version_available

    if 'build' in comparable_version:
        fix_version = version_available.replace(")", "")
        a, b = fix_version.split(" (build ")
        if a.count('.') == 1:
            a = a + '.0'

        comparable_version = a + '.' + b

    is_compatible = LooseVersion(plugin_version) == LooseVersion(comparable_version)

    if not is_compatible:
        if (LooseVersion(plugin_version) > LooseVersion(comparable_version)):
            output = 'Bigger'
        else:
            output = 'Lower'

    return output


def get_link_from_repo(repo_url, key, version):
    final_url = 'not-found'
    html_doc = urllib2.urlopen(repo_url).read()
    parser = LinksParser()
    parser.feed(html_doc)
    all_data = parser.data

    for data in all_data:
        match = re.search('sonar-(.*)-plugin/', data)
        if match is not None:
            plugin = match.group(1)
            current_key = re.sub('-', '', plugin)
            if current_key == key:
                ready_data = re.sub(r'.*sonar', 'sonar', data)
                final_url = repo_url + data.lstrip() + re.sub('/', '', ready_data) + '-' + version + '.jar'
                return final_url

    return final_url


def is_plugin_update_available(module, sonar_url, updates_list_api, installed_list_api):
    is_available = False
    version_installed = 'not-found'
    url = sonar_url + installed_list_api
    response = requests.get(url, auth=HTTPBasicAuth(module.params['username'],
                                                    module.params['password']))
    json_obj = response.json()

    for plugin in json_obj['plugins']:
        if plugin['name'] == module.params['name']:
            version_installed = plugin['version']

    comparison = compare_plugins_version(module.params['version'],
                                         version_installed)

    if comparison == 'Equal':
        module.exit_json(changed=False, stdout='FAILED: Version already installed')
    elif comparison == 'Lower':
        is_available = True
    else:
        url = sonar_url + updates_list_api
        response = requests.get(url, auth=HTTPBasicAuth(module.params['username'], module.params['password']))
        json_obj = response.json()
        for plugin in json_obj['plugins']:
            if plugin['name'] == module.params['name']:
                for update in plugin['updates']:
                    if compare_plugins_version(module.params['version'], update['release']['version']) == 'Equal':
                        if not update['requires'] and update['status'] == 'COMPATIBLE':
                            is_available = True

    return is_available


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str'),
            state=dict(type='str', choices=['installed', 'removed', 'latest']),
            version=dict(type='str'),
            custom_url=dict(type='str'),
            hostname=dict(default='localhost', type='str'),
            username=dict(default='admin', type='str'),
            password=dict(default='admin', type='str', no_log=True),
            pending_dir=dict(default='/usr/local/sonar/extensions/downloads/', type='str'),
            sonar_port=dict(default='9000', type='int')
        ),
        mutually_exclusive=[['custom_url', 'state']]
    )

    available_list_api = '/api/plugins/available'
    installed_list_api = '/api/plugins/installed'
    updates_list_api = '/api/plugins/updates'

    install_api = '/api/plugins/install'
    remove_api = '/api/plugins/uninstall'
    update_api = '/api/plugins/update'

    sonarsource_plugins_repo = 'https://binaries.sonarsource.com/Distribution/'

    state = module.params['state']
    sonar_url = 'http://' + module.params['hostname'] + ':' + str(module.params['sonar_port'])
    plugin_data = {}

    if module.params['custom_url']:
        status_pending = 'custom'
        key = download_custom_plugin(module.params['custom_url'], module.params['pending_dir'], status_pending)
        if key != 'not-found':
            if is_plugin_pending(key, status_pending, module):
                msg = 'SUCCESS: The plugin with key={} is pending'.format(key)
                module.exit_json(changed=True, stdout=msg)
        else:
            module.exit_json(changed=True,
                             stdout='SUCCESS: The plugin was downloaded, but we can not check if it pending')

    if is_plugin_installed(module, sonar_url, installed_list_api):
        plugin_data['key'] = get_key_by_name(sonar_url, installed_list_api, module)
    else:
        plugin_data['key'] = get_key_by_name(sonar_url, available_list_api, module)

    if plugin_data['key'] == 'not-found':
        module.exit_json(changed=False, stdout='FAILED: Plugin not found')

    if state == 'removed' or state == 'latest':
        if module.params['version']:
            module.fail_json(msg='version field required only if state=installed')

        status_pending = 'removing'

        if state == 'removed':
            apply_post_api(sonar_url, remove_api, module, plugin_data, status_pending)
        else:
            status_pending = 'updating'
            apply_post_api(sonar_url, update_api, module, plugin_data, status_pending)
    else:
        status_pending = 'installing'
        is_available = is_plugin_installation_available(module, sonar_url, available_list_api)
        if not module.params['version']:
            if is_available:
                apply_post_api(sonar_url, install_api, module, plugin_data, status_pending)
        else:
            link = get_link_from_repo(sonarsource_plugins_repo, plugin_data['key'], module.params['version'])
            if link == 'not-found':
                module.exit_json(changed=False, stdout='FAILED: Plugin url not found in sonarsource repo')

            if not is_plugin_installed(module, sonar_url, installed_list_api):
                if is_available:
                    download_custom_plugin(link, module.params['pending_dir'], status_pending)
                    if is_plugin_pending(plugin_data['key'], status_pending, module):
                        module.exit_json(changed=True, stdout='SUCCESS: The plugin version is installed')
            else:
                status_pending = 'updating'
                if is_plugin_update_available(module, sonar_url, updates_list_api, installed_list_api):
                    download_custom_plugin(link, module.params['pending_dir'], status_pending)
                    if is_plugin_pending(plugin_data['key'], status_pending, module):
                        module.exit_json(changed=True, stdout='SUCCESS: The plugin version changed')
                else:
                    module.exit_json(changed=False,
                                     stdout='FAILED: This version not exist or not available for this sonar server')


if __name__ == "__main__":
    main()
