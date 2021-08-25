# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

DEPS = [
    'chromite',
    'depot_tools/gitiles',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/swarming',
]


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


def GenTests(api):
  yield api.test(
      'basic',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.properties(cbb_config='auron-paladin'),
      api.buildbucket.try_build(
          'basic',
          git_repo='https://chromium.googlesource.com/chromiumos/manifest',
          revision='deadbeef'),
  )

  yield api.test(
      'pass_repo_sync_args',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.properties(cbb_config='auron-paladin', repo_sync_args=['-j16']),
      api.buildbucket.try_build(
          'basic',
          git_repo='https://chromium.googlesource.com/chromiumos/manifest',
          revision='deadbeef'),
  )

  yield api.test(
      'chromiumos_coverage',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
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
      'pass_branch',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.properties(cbb_config='auron-paladin', branch='foobarnch'),
      api.post_process(post_process.DropExpectation),
      api.buildbucket.try_build(
          'basic',
          git_repo='https://chromium.googlesource.com/chromiumos/manifest',
          revision='deadbeef'),
  )
