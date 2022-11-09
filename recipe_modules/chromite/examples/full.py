# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process
from PB.chromiumos import common
from PB.recipe_modules.chromeos.goma.goma import GomaProperties

DEPS = [
    'chromite',
    'depot_tools/gitiles',
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/swarming',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.chromite.set_config('chromiumos_coverage')

  # goma.py checkout/build exercise.
  api.chromite.checkout(branch=api.properties.get('branch', None))
  api.chromite.setup_board('amd64-generic', args=['--cache-dir', '.cache'])
  api.chromite.build_packages('amd64-generic')
  api.chromite.cros_sdk('cros_sdk', ['echo', 'hello'],
                        environ={'var1': 'value'})

  # Normal build exercise.
  api.chromite.cbuildbot('cbuildbot', 'amd64-generic-full',
                         args=['--clobber', '--build-dir', '/here/there'])

  # Update or install goma client via cipd.
  api.chromite.m.goma.initialize()
  api.chromite.m.goma.client_version = api.properties.get(
      'cbb_goma_client_type')
  api.chromite.run()

  api.assertions.assertEqual(api.chromite.depot_tools_pin,
                             'c49a7334d30256abc1fc1e56d79615a220028998')
  # A second time to hit the caching.
  api.assertions.assertEqual(api.chromite.depot_tools_pin,
                             'c49a7334d30256abc1fc1e56d79615a220028998')


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(cbb_config='auron-paladin'),
      api.buildbucket.try_build(
          'basic',
          git_repo='https://chromium.googlesource.com/chromiumos/manifest',
          revision='deadbeef'),
  )
  yield api.test(
      'goma',
      api.properties(cbb_config='auron-paladin'),
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                  )
          }),
      api.buildbucket.try_build(
          'basic',
          git_repo='https://chromium.googlesource.com/chromiumos/manifest',
          revision='deadbeef'),
  )
  yield api.test(
      'goma-client-json',
      api.properties(cbb_config='auron-paladin'),
      api.properties(
          **{
              '$chromeos/goma':
                  GomaProperties(
                      goma_approach=common.GomaConfig.RBE_PROD,
                      enable_goma_client_json=True,
                  )
          }),
      api.buildbucket.try_build(
          'basic',
          git_repo='https://chromium.googlesource.com/chromiumos/manifest',
          revision='deadbeef'),
  )

  yield api.test(
      'pass-repo-sync-args',
      api.properties(cbb_config='auron-paladin', repo_sync_args=['-j16']),
      api.buildbucket.try_build(
          'basic',
          git_repo='https://chromium.googlesource.com/chromiumos/manifest',
          revision='deadbeef'),
  )

  yield api.test(
      'chromiumos-coverage',
      api.properties(clobber=None,
                     cbb_config='cros-x86-generic-tot-chrome-pfq-informational',
                     cbb_master_build_id='24601', cbb_branch='main',
                     config_repo='https://fake.googlesource.com/myconfig/repo'),
      api.buildbucket.try_build(
          'chromiumos.coverage', build_number=12345,
          git_repo='https://chromium.googlesource.com/chromium/src',
          revision='b8819267417da248aa4fe829c5fcf0965e17b0c3'),
      api.post_process(post_process.MustRun, 'setup board'),
      api.post_process(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'pass-branch',
      api.properties(cbb_config='auron-paladin', branch='foobarnch'),
      api.post_process(post_process.DropExpectation),
      api.buildbucket.try_build(
          'basic',
          git_repo='https://chromium.googlesource.com/chromiumos/manifest',
          revision='deadbeef'),
  )
