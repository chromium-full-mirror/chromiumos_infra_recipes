#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import os
import subprocess


def main():
  here = os.path.dirname(__file__)
  repo_root = os.path.join(here, '..')
  stubs_root = os.path.abspath(os.path.join(here, 'stubs'))

  os.chdir(repo_root)

  output = subprocess.check_output(['./recipes.py', 'doc', '--kind', 'jsonpb'])

  data = json.loads(output)

  for name, module in data['recipe_modules'].items():
    deps = [dep['name'] for dep in module['deps']['module_links']]
    if not deps:
      print('No DEPS for %s; skipping' % name)
      continue

    print('Processing %s' % name)
    stub_path = os.path.join(stubs_root, module['name'], 'api.pyi')
    stub_dir = os.path.dirname(stub_path)
    if not os.path.exists(stub_dir):
      os.makedirs(stub_dir)
    with open(stub_path, 'w') as stub:
      for dep in deps:
        stub.write('import %s.api\n' % dep)
      stub.write('\n')

      stub.write('class ModuleDeps:\n')
      for dep in deps:
        # FIXME: find RecipeApi subclass instead of relying on naming convention
        dep_class = ''.join(x.capitalize() for x in dep.split('_')) + 'Api'
        stub.write('  %s: %s.api.%s\n' % (dep, dep, dep_class))
      stub.write('\n')

      stub.write('class %s:\n' % module['api_class']['name'])
      stub.write('  m: ModuleDeps')

if __name__ == '__main__':
    main()
