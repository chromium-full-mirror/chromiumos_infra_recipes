# Copyright 2020 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
import json
import zlib

DEPS = [
    'cros_infra_config',
    'chromite',
    'depot_tools/gitiles',
    'recipe_engine/json',
    'recipe_engine/properties',
]

# Map group name to 'chromite' configuration name.
_GROUP_CONFIG_MAP = {
    'chromiumos.tryserver': {
        'group_config': 'master_chromiumos_tryserver',
    },
}

# Testing: Tryjob data file JSON.
_TRYJOB_DATA = """
{
  "name": "12345",
  "email": "testauthor@fake.chromium.org",
  "extra_args": [
    "--timeout",
    "14400",
    "--remote-trybot",
    "--remote-version=4"
  ]
}
"""

# JSON string containing sufficient Chromite configuration layout for our test
# configs.
_CHROMITE_CONFIG = {
    '_default': {
        'build_type': 'undefined',
    },
    '_templates': {
        'full': {
            'build_type': 'full',
        },
        'paladin': {
            'build_type': 'paladin',
        },
    },
    'x86-generic-full': {
        '_template': 'full',
    },
    'internal-paladin': {
        '_template': 'paladin',
        'internal': True,
    },
}


def RunSteps(api):
  # The 'cbuildbot' config name to build is the name of the builder.
  #
  # TODO(dnj): After we fully switch to BuildBucket scheduling, load the config
  #            name from the BuildBucket job instead of `cbb_config` build
  #            property. We can't do this yet b/c the job description can
  #            specify multiple configs in one tryjob, so there's no way for us
  #            to know which one we are.
  cbb_config_name = api.properties.get('cbb_config')
  assert cbb_config_name, "No configuration name specified."

  # Get parameters specified in the tryjob description.
  tryjob_args = api.properties.get('cbb_extra_args', [])
  # If tryjob_args is a string, translate from json to list.
  if hasattr(tryjob_args, 'startswith'):
    if tryjob_args.startswith('z:'):
      tryjob_args = zlib.decompress(base64.b64decode(tryjob_args[2:]))
    tryjob_args = api.json.loads(tryjob_args)

  # Apply our generic configuration.
  api.chromite.configure(api.properties, _GROUP_CONFIG_MAP,
                         CBB_EXTRA_ARGS=tryjob_args)
  api.chromite.c.cbb.config = cbb_config_name

  # Load the Chromite configuration for our target.
  api.chromite.checkout_chromite()

  # Update or install goma client via cipd.
  api.chromite.m.goma.initialize()

  # Run our 'cbuildbot'.
  api.chromite.run(args=[])


def GenTests(api):
  common_test_data = sum([
      api.cros_infra_config.current_builder_group('chromiumos.tryserver'),
      api.properties(
          repository='https://chromium.googlesource.com/chromiumos/tryjobs.git',
          revision=api.gitiles.make_hash('test'),
          slave_name='test',
      ),
  ], api.empty_test_data())

  # Test a CrOS tryjob.
  yield api.test(
      'external',
      api.properties(
          buildername='full', cbb_config='x86-generic-full',
          cbb_extra_args='["--timeout", "14400", "--remote-trybot",'
          '"--remote-version=4"]'),
      common_test_data,
  )

  yield api.test(
      'internal',
      api.properties(
          buildername='paladin', cbb_config='internal-paladin',
          cbb_extra_args='["--timeout", "14400", "--remote-trybot",'
          '"--remote-version=4"]'),
      common_test_data,
  )

  yield api.test(
      'swarming',
      api.properties(
          buildername='paladin', cbb_config='internal-paladin', cbb_extra_args=[
              "--timeout", "14400", "--remote-trybot", "--remote-version=4"
          ]),
      common_test_data,
  )

  yield api.test(
      'release',
      api.properties(
          buildername='paladin', cbb_config='x86-generic-full',
          cbb_branch='release-R55-9999.B',
          cbb_extra_args='["--timeout", "14400", "--remote-trybot",'
          '"--remote-version=4"]'),
      common_test_data,
  )

  yield api.test(
      'release_branch_one_param',
      api.properties(
          buildername='paladin', cbb_config='x86-generic-full',
          cbb_branch='master', cbb_extra_args=json.dumps([
              '--timeout', '14400', '--remote-trybot', '--remote-version=4',
              '--branch=release-R00-0000.B'
          ])),
      common_test_data,
  )

  yield api.test(
      'release_branch_two_params',
      api.properties(
          buildername='paladin', cbb_config='x86-generic-full',
          cbb_branch='master', cbb_extra_args=json.dumps([
              '--timeout', '14400', '--remote-trybot', '--remote-version=4',
              '--branch', 'release-R00-0000.B'
          ])),
      common_test_data,
  )

  yield api.test(
      'pre_git_cache_release',
      api.properties(
          buildername='paladin', cbb_config='x86-generic-full',
          cbb_branch='release-R54-8743.B',
          cbb_extra_args='["--timeout", "14400", "--remote-trybot",'
          '"--remote-version=4"]'),
      common_test_data,
  )

  # Test a CrOS tryjob with compressed "cbb_extra_args".
  yield api.test(
      'basic_compressed',
      api.properties(
          buildername='full', cbb_config='x86-generic-full', cbb_extra_args=(
              'z:eJyLVtLVLcnMTc0vLVHSUVAyNDExMAAxdHWLUnPzS1J1S4oqk/JLUITKUouKM'
              '/PzbE2UYgFJaBNI')),
      common_test_data,
  )

  # Test a config that is not registered in Chromite.
  yield api.test(
      'unknown_config',
      api.properties(
          buildername='etc', cbb_config='xxx-fakeboard-fakebuild',
          cbb_extra_args='["--timeout", "14400", "--remote-trybot",'
          '"--remote-version=4"]'),
      common_test_data,
  )

  # Test a config with buildbucket properties
  yield api.test(
      'pre_cq_buildbucket_config',
      api.properties(
          buildername='pre-cq', cbb_config='binhost-pre-cq',
          cbb_extra_args='["--timeout", "14400", "--remote-trybot",'
          '"--remote-version=4"]',
          buildbucket=json.dumps({'build': {
              'id': '12345'
          }})),
      common_test_data,
  )
