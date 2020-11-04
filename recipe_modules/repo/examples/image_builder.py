# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'repo',
]

from google.protobuf import json_format

from PB.recipe_modules.chromeos.repo.examples import common
from PB.recipe_modules.chromeos.repo.examples.image_builder import (
    ImageBuilderProperties)

PROPERTIES = ImageBuilderProperties

# This example shows the normal flow of events for build_menu.


def RunSteps(api, properties):
  repo_root = api.path['start_dir'].join('repo')
  api.path.mock_add_paths(repo_root.join('.repo'))

  with api.context(cwd=repo_root.join('manifest-internal')):
    init_opts = json_format.MessageToDict(properties.init_opts,
                                          preserving_proto_field_name=True)
    manifest_url = init_opts.pop('manifest_url', 'http://manifest_url')
    local_manifest = init_opts.pop('local_manifest', None)
    if local_manifest:
      init_opts['local_manifest'] = api.repo.LocalManifest(
          local_manifest['repo'], local_manifest['path'])
    sync_opts = json_format.MessageToDict(properties.sync_opts,
                                          preserving_proto_field_name=True)

    projects = list(properties.projects)
    checkout_path = api.path['cleanup'].join('ensure')
    if init_opts.get('manifest_name'):
      manifest_name = checkout_path.join(init_opts['manifest_name'])
      init_opts['manifest_name'] = manifest_name
      sync_opts['manifest_name'] = manifest_name
    api.repo.ensure_synced_checkout(checkout_path, manifest_url,
                                    init_opts=init_opts, sync_opts=sync_opts,
                                    projects=projects)

    manifest_data = ('<manifest></manifest>' if not properties.manifest_data
                     else properties.manifest_data.encode('utf-8'))

    with api.step.nest('sync to snapshot'):
      api.repo.sync_manifest(manifest_url, manifest_data=manifest_data,
                             detach=True, optimized_fetch=True, retry_fetches=8)


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'with-manifest-name',
      api.properties(
          ImageBuilderProperties(
              init_opts=common.InitOpts(manifest_name='manifest'),
              sync_opts=common.SyncOpts(manifest_name='manifest'))))

  local_manifest = common.LocalManifest(
      repo='https://chrome-internal.googlesource.com/testproject1',
      path='local_manifest.xml',
  )
  yield api.test(
      'with-args',
      api.properties(
          ImageBuilderProperties(
              projects=['chromiumos/config', 'chromeos/project/puff/duffy'],
              init_opts=common.InitOpts(
                  manifest_branch='mybranch',
                  manifest_name='snapshot.xml',
                  reference='/preload/chromeos',
                  groups=['group1', 'group2'],
                  depth=10,
                  repo_url='http://repo_url',
                  repo_branch='next',
                  local_manifest=local_manifest,
                  verbose=True,
              ), sync_opts=common.SyncOpts(
                  force_sync=True, detach=True, current_branch=True, jobs=99,
                  manifest_name='snapshot.xml', no_tags=True,
                  optimized_fetch=True, cache_dir='/tmp/cache', retry_fetches=8,
                  verbose=True, no_manifest_update=True))))
