#!/usr/bin/python

# 2018, Shay Shevach <shshevac@redhat.com>

from __future__ import absolute_import, division, print_function
__metaclass__ = type

ANSIBLE_METADATA = {
    'metadata_version': '1.0',
    'supported_by': 'community',
    'status': ['preview']
}

DOCUMENTATION = '''
---
module: sonar_plgn
version_added: "1.0"
description: |
    Manage plugins installation in a sonarqube server as well as removal or
    update.
short_description: Manage plugins in SonarQube server.
author: "Shay Shevach"
options:
    name:
        description: |
            plugin name as it is represented by Sonar.
    state:
        description: |
            Whether to install or remove, update or downgrade a plugin.
    version:
        description: |
            The version of the plugin.
    username:
        description: |
            Sonarqube user that has admin privileges.
    password:
        description: |
            Password of the above user. 
    custom_url:
        description: |
            The plugin download URL if we install from a source that is
            not sonarsource.
    TODO
'''

EXAMPLES = '''
- name: Install C# plugin
  sonar_plgn:
      name: csharp
      state: installed
      username: admin
      password: admin
'''

RETURN = ''' # '''

from ansible.module_utils.basic import AnsibleModule
from os import path
import json
import requests
from requests.auth import HTTPBasicAuth
import os
import urllib
from string import digits
from distutils.version import LooseVersion
import re
import urllib2
from StringIO import StringIO
# require "pip install beautifulsoup4"
from bs4 import BeautifulSoup

def apply_post_api(sonar_url, api, module, plugin_data, status):
    url = sonar_url + api
    requests.post(url, data=plugin_data, auth=HTTPBasicAuth(module.params['username'], module.params['password']))

    msg = switch_msg(status)
 
    if is_plugin_pending(module.params['name'], status, module):
       module.exit_json(changed=True, stdout=msg)

def switch_msg(status):
    return {
        'installing': 'SUCCESS: The plugin is installed',
        'updating': 'SUCCESS: The plugin was removed',
        'removing': 'SUCCESS: The plugin latest version is installed',
    }[status]

def get_key_by_name(sonar_url, api, module):
    key = 'not-found'
    url = sonar_url + api
    response = requests.get(url, auth=HTTPBasicAuth(module.params['username'], module.params['password']))
    json_obj = response.json()

    for plugin in json_obj['plugins']:
        if plugin['name'] == module.params['name']:
            key = plugin['key']

    return key

def is_plugin_pending(plugin_name, status, module):
    is_pending = False
    pending_api = '/api/plugins/pending'
    hostname = module.params['hostname']
    port = module.params['sonar_port']

    url = 'http://' + hostname + ':' + str(port) + pending_api
    response = requests.get(url, auth=HTTPBasicAuth(module.params['username'], module.params['password']))
    json_obj = response.json()
        
    for stat in json_obj[status]:
        if stat['name'] == plugin_name:
           is_pending = True

    return is_pending

def download_custom_plugin(plugin_url, download_folder):
    filename = os.path.basename(plugin_url)
    filename_path = download_folder + filename
    urllib.urlretrieve(plugin_url, filename_path)
    #if module.params['state']:
      #status =  
    return 'SUCCESS'
   
def is_plugin_installed(module, sonar_url, installed_list_api):
    is_installed = False
    url = sonar_url + installed_list_api
    response = requests.get(url, auth=HTTPBasicAuth(module.params['username'], module.params['password']))
    json_obj = response.json() 
    for plugin in json_obj['plugins']:                                          
        if plugin['name'] == module.params['name']:
           is_installed = True

    return is_installed
 
def is_plugin_installation_available(module, sonar_url, available_list_api):
    is_available = False
    url = sonar_url + available_list_api
 
    response = requests.get(url, auth=HTTPBasicAuth(module.params['username'], module.params['password']))
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
    soup = BeautifulSoup(html_doc, 'html.parser')
     
    for line in soup.find_all('a'):
        data = line.string
        match = re.search('sonar-(.*)-plugin/', data)
        if match != None:
           plugin = match.group(1)
           current_key = re.sub('-', '', plugin)
           if current_key == key:
              ready_data = re.sub(r'.*sonar', 'sonar', data)
              final_url = repo_url + re.sub('/', '', ready_data) + '-' + version + '.jar'
              return final_url
 
    return final_url

def is_plugin_update_available(module, sonar_url, updates_list_api, installed_list_api):
    is_available = False
    version_installed = 'not-found'
    url = sonar_url + installed_list_api                                        
    response = requests.get(url, auth=HTTPBasicAuth(module.params['username'], module.params['password']))
    json_obj = response.json()                                                  

    for plugin in json_obj['plugins']:                                          
        if plugin['name'] == module.params['name']:
           version_installed = plugin['version']

    comparison = compare_plugins_version(module.params['version'], version_installed) 
    
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
        mutually_exclusive = [['custom_url', 'state']]
    )

    # GET requests
    available_list_api    = '/api/plugins/available'
    installed_list_api    = '/api/plugins/installed'
    updates_list_api      = '/api/plugins/updates'

    # POST requests
    install_api           = '/api/plugins/install'
    remove_api            = '/api/plugins/uninstall'
    update_api            = '/api/plugins/update'
    
    sonarsource_plugins_repo = 'https://binaries.sonarsource.com/Distribution/'
    
    plugin_name = module.params['name']
    state       = module.params['state']
    sonar_url   = 'http://' + module.params['hostname'] + ':' + str(module.params['sonar_port'])
    plugin_data = {}

    if module.params['custom_url']:
       output = download_custom_plugin(module.params['custom_url'], module.params['pending_dir'])
       if output == 'SUCCESS':
          module.exit_json(changed=True, stdout='SUCCESS: The plugin is installed')
    
    if is_plugin_installed(module, sonar_url, installed_list_api):
       plugin_data['key'] = get_key_by_name(sonar_url, installed_list_api, module) 
    else:
       plugin_data['key'] = get_key_by_name(sonar_url, available_list_api, module)

    if plugin_data['key'] == 'not-found':
       module.exit_json(changed=False, stdout='FAILED: Plugin not found')

    if state == 'removed' or state == 'latest':
       if module.params['version']:
          module.fail_json(msg='version field required only if state=installed')

       # status - how sonar api see it
       # state  - what the module user want for the plugin to be 
       status = 'removing'

       if state == 'removed':
          apply_post_api(sonar_url, remove_api, module, plugin_data, status)
       else:
          status = 'updating'
          apply_post_api(sonar_url, update_api, module, plugin_data, status)
    else:
       status = 'installing'
       is_available = is_plugin_installation_available(module, sonar_url, available_list_api)
       if not module.params['version']:
          if is_available:
             apply_post_api(sonar_url, install_api, module, plugin_data, status)
       else:
          link = get_link_from_repo(sonarsource_plugins_repo, plugin_data['key'], module.params['version'])
          if link == 'not-found':
             module.exit_json(changed=False, stdout='FAILED: Plugin url not found in sonarsource repo')

          if not is_plugin_installed(module, sonar_url, installed_list_api):
             if is_available:
                output = download_custom_plugin(link, module.params['pending_dir']) 
                if is_plugin_pending(plugin_name, status, module) and output == 'SUCCESS': 
                   module.exit_json(changed=True, stdout='SUCCESS: The plugin is installed')
          else:
             status = 'updating'
             if is_plugin_update_available(module, sonar_url, updates_list_api, installed_list_api):
                output = download_custom_plugin(link, module.params['pending_dir']) 
                if is_plugin_pending(plugin_name, status, module) and output == 'SUCCESS':
                   module.exit_json(changed=True, stdout='SUCCESS: The plugin version is installed')
                
             
    # check custom download status
    # check download url

if __name__ == "__main__":
    main()
