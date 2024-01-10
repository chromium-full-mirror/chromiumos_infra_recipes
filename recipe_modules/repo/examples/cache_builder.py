# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf.json_format import MessageToDict
from PB.recipe_modules.chromeos.repo.examples import common
from PB.recipe_modules.chromeos.repo.examples.image_builder import ImageBuilderProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = ImageBuilderProperties

# This example shows the normal flow of events for build_menu.


def RunSteps(api, properties):
  repo_root = api.path['start_dir'].join('repo')
  api.path.mock_add_paths(repo_root.join('.repo'))

  with api.context(cwd=repo_root.join('manifest-internal')):
    init_opts = MessageToDict(properties.init_opts,
                              preserving_proto_field_name=True)
    init_opts['manifest_branch'] = 'snapshot'
    manifest_url = init_opts.pop('manifest_url', 'http://manifest_url')
    sync_opts = MessageToDict(properties.sync_opts,
                              preserving_proto_field_name=True)

    repo_state_path = repo_root.join('.recipes_state.json')
    api.path.mock_add_paths(repo_state_path)
    api.repo.ensure_synced_checkout(repo_root, manifest_url,
                                    init_opts=init_opts, sync_opts=sync_opts,
                                    final_cleanup=True)


def GenTests(api):
  yield api.test('basic')

  yield api.test(
      'no-prune',
      api.properties(
          sync_opts=common.SyncOpts(
              force_sync=True, detach=True, current_branch=True, jobs=20,
              no_tags=True, optimized_fetch=True, retry_fetches=8, verbose=True,
              no_manifest_update=True, force_remove_dirty=True, prune=False)),
  )
