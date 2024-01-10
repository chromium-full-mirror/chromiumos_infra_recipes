# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf.json_format import MessageToDict

from PB.chromiumos.repo_cache_state import RepoState
from PB.recipe_modules.chromeos.repo.examples import common
from PB.recipe_modules.chromeos.repo.examples.image_builder import ImageBuilderProperties

from recipe_engine import post_process

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
    local_manifest = init_opts.pop('local_manifest', None)
    if local_manifest:
      init_opts['local_manifests'] = [
          api.repo.LocalManifest(local_manifest['repo'], local_manifest['path'],
                                 branch=init_opts.get('manifest_branch'))
      ]
    sync_opts = MessageToDict(properties.sync_opts,
                              preserving_proto_field_name=True)

    projects = list(properties.projects)
    checkout_path = api.path['cleanup'].join('ensure')
    if init_opts.get('manifest_name'):
      manifest_name = checkout_path.join(init_opts['manifest_name'])
      init_opts['manifest_name'] = manifest_name
      sync_opts['manifest_name'] = manifest_name
    repo_state_path = checkout_path.join('.recipes_state.json')
    api.path.mock_add_paths(repo_state_path)
    api.repo.ensure_synced_checkout(checkout_path, manifest_url,
                                    init_opts=init_opts, sync_opts=sync_opts,
                                    projects=projects)

    manifest_data = ('<manifest></manifest>' if not properties.manifest_data
                     else properties.manifest_data.encode('utf-8'))

    with api.step.nest('sync to snapshot'):
      api.repo.sync_manifest(manifest_url, manifest_data=manifest_data,
                             current_branch=True, detach=True,
                             optimized_fetch=True, retry_fetches=8)


def WithManifestNameTest(api, state_name, state):
  return api.test(
      'with-manifest-name-{}'.format(state_name),
      api.properties(
          ImageBuilderProperties(
              init_opts=common.InitOpts(manifest_name='manifest'),
              sync_opts=common.SyncOpts(manifest_name='manifest'))),
      api.repo.repo_current_state(state))


def WithArgsTest(api, state_name, state, local_manifest):
  return api.test(
      'with-args-{}'.format(state_name),
      api.properties(
          ImageBuilderProperties(
              projects=['chromiumos/config', 'chromeos/project/puff/duffy'
                       ], init_opts=common.InitOpts(
                           manifest_name='snapshot.xml',
                           reference='/preload/chromeos',
                           groups=['group1', 'group2'],
                           depth=10,
                           repo_url='http://repo_url',
                           repo_branch='next',
                           local_manifest=local_manifest,
                           verbose=True,
                       ), sync_opts=common.SyncOpts(
                           force_sync=True, detach=True, current_branch=True,
                           jobs=99, manifest_name='snapshot.xml', no_tags=True,
                           optimized_fetch=True, retry_fetches=8, verbose=True,
                           no_manifest_update=True, force_remove_dirty=True,
                           prune=True))), api.repo.repo_current_state(state))


def WithretryTest(api, state_name, state, local_manifest):
  return api.test(
      'with-retry-{}'.format(state_name),
      api.properties(
          ImageBuilderProperties(
              projects=['chromiumos/config', 'chromeos/project/puff/duffy'
                       ], init_opts=common.InitOpts(
                           manifest_name='snapshot.xml',
                           reference='/preload/chromeos',
                           groups=['group1', 'group2'],
                           depth=10,
                           repo_url='http://repo_url',
                           repo_branch='next',
                           local_manifest=local_manifest,
                           verbose=True,
                       ), sync_opts=common.SyncOpts(
                           force_sync=True, detach=True, current_branch=True,
                           jobs=99, manifest_name='snapshot.xml', no_tags=True,
                           optimized_fetch=True, retry_fetches=8, verbose=True,
                           no_manifest_update=True, force_remove_dirty=True,
                           prune=True))), api.repo.repo_current_state(state))


def WithNonePruneTest(api, state_name, state):
  return api.test(
      'with-none-prune-{}'.format(state_name),
      api.properties(
          ImageBuilderProperties(
              projects=['chromiumos/config', 'chromeos/project/puff/duffy'
                       ], init_opts=common.InitOpts(
                           manifest_name='snapshot.xml',
                           reference='/preload/chromeos',
                           groups=['group1', 'group2'],
                           depth=10,
                           repo_url='http://repo_url',
                           repo_branch='next',
                           verbose=True,
                       ), sync_opts=common.SyncOpts(
                           force_sync=True, detach=True, current_branch=True,
                           jobs=99, manifest_name='snapshot.xml', no_tags=True,
                           optimized_fetch=True, retry_fetches=8, verbose=True,
                           no_manifest_update=True, force_remove_dirty=True,
                           prune=None))), api.repo.repo_current_state(state))


def GenTests(api):
  yield api.test('basic-failure', api.repo.fail_repo_sync(True))

  yield api.test('basic-unspecified',
                 api.repo.repo_current_state(RepoState.STATE_UNSPECIFIED))
  yield api.test('basic-clean',
                 api.repo.repo_current_state(RepoState.STATE_CLEAN))
  yield api.test('basic-dirty',
                 api.repo.repo_current_state(RepoState.STATE_DIRTY))
  yield api.test('basic-recovery',
                 api.repo.repo_current_state(RepoState.STATE_RECOVERY))

  yield api.test('basic-manifest-mismatch',
                 api.repo.repo_manifest_branch('mismatch'))

  yield api.test(
      'with-disable-repo-verify',
      api.repo.repo_current_state(RepoState.STATE_UNSPECIFIED),
      api.properties(**{'$chromeos/repo': {
          'disable_repo_verify': True
      }}),
      api.post_check(post_process.StepCommandContains,
                     'ensure synced checkout.repo init', ['--no-repo-verify']),
      api.post_check(
          post_process.StepCommandContains,
          'ensure synced checkout.repo binary update.repo selfupdate',
          ['--no-repo-verify']),
      api.post_check(post_process.StepCommandContains,
                     'sync to snapshot.repo init', ['--no-repo-verify']),
  )

  local_manifest = common.LocalManifest(
      repo='https://chrome-internal.googlesource.com/testproject1',
      path='local_manifest.xml',
  )

  yield WithManifestNameTest(api, 'unspecified', RepoState.STATE_UNSPECIFIED)
  yield WithManifestNameTest(api, 'clean', RepoState.STATE_CLEAN)
  yield WithManifestNameTest(api, 'dirty', RepoState.STATE_DIRTY)
  yield WithManifestNameTest(api, 'recovery', RepoState.STATE_RECOVERY)

  yield WithArgsTest(api, 'unspecified', RepoState.STATE_UNSPECIFIED,
                     local_manifest)
  yield WithArgsTest(api, 'clean', RepoState.STATE_CLEAN, local_manifest)
  yield WithArgsTest(api, 'dirty', RepoState.STATE_DIRTY, local_manifest)
  yield WithArgsTest(api, 'recovery', RepoState.STATE_RECOVERY, local_manifest)

  yield WithretryTest(api, 'unspecified', RepoState.STATE_UNSPECIFIED,
                      local_manifest)
  yield WithretryTest(api, 'clean', RepoState.STATE_CLEAN, local_manifest)
  yield WithretryTest(api, 'dirty', RepoState.STATE_DIRTY, local_manifest)
  yield WithretryTest(api, 'recovery', RepoState.STATE_RECOVERY, local_manifest)

  yield WithNonePruneTest(api, 'unspecified', RepoState.STATE_UNSPECIFIED)

  default_override = 'http://my-default/repo-url'
  yield api.test(
      'with-default-repo-url',
      api.repo.repo_current_state(RepoState.STATE_UNSPECIFIED),
      api.properties(
          **{'$chromeos/repo': {
              'default_repo_url': default_override
          }}),
      api.post_check(post_process.StepCommandContains,
                     'ensure synced checkout.repo init',
                     [f'--repo-url={default_override}']),
      api.post_check(post_process.StepCommandContains,
                     'sync to snapshot.repo init',
                     [f'--repo-url={default_override}']),
  )
