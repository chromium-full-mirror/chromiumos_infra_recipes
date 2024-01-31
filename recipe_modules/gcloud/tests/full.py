# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from PB.recipe_modules.chromeos.gcloud.gcloud import SourceCacheAction

DEPS = [
    'recipe_engine/assertions',
    'gcloud',
]


GCE_PROJECT = 'chromeos-gce-tests'


def RunSteps(api):
  _ = api.gcloud.infra_host
  api.gcloud.set_gce_project(project=GCE_PROJECT)
  api.gcloud.auth_list()
  api.gcloud.create_image('image-name', source_uri='source-uri',
                          licenses=['license'])
  api.gcloud.delete_image('image-name')
  api.gcloud.create_instance('image-name', project=GCE_PROJECT,
                             machine='n1-standard-4', zone='us-central1-b',
                             network='chromeos-gce-tests', subnet='us-central1')
  api.gcloud.create_instance('image-name', project=GCE_PROJECT,
                             machine='n1-standard-4', zone='us-central1-b',
                             network='chromeos-gce-tests', subnet='us-central1',
                             external_ip=True)
  api.gcloud.attach_disk(name='test-disk', instance='image-name',
                         disk='test-disk', zone='us-central1-b')
  api.gcloud.detach_disk(instance='image-name', disk='test-disk',
                         zone='us-central1-b')
  api.gcloud.get_instance_serial_output('image-name', project=GCE_PROJECT,
                                        zone='us-central1-a')
  api.gcloud.delete_instance('image-name', project=GCE_PROJECT,
                             zone='us-central1-a')

  with api.assertions.assertRaises(ValueError):
    api.gcloud.create_image('image-name')  # No source specified

  versions_exists_tests = {
      'chromiumos-main-16287984': True,
      'staging-chromiumos-release-r93-14092-b-16287710': True,
      'chrome-release-r93-14092-b-99999999': False,
  }
  for test, result in versions_exists_tests.items():
    api.assertions.assertEqual(result,
                               api.gcloud.disk_exists(disk=test, zone='foo'))
    api.assertions.assertEqual(result, api.gcloud.image_exists(image=test))

  suffix_test = [
      {
          'cache': 'chromiumos',
          'branch': 'main',
          'result': 'cros',
      },
      {
          'cache': 'chromeos',
          'branch': 'main',
          'result': 'internal-cros',
      },
      {
          'cache': 'chrome',
          'branch': 'main',
          'result': 'cr',
      },
      {
          'cache': 'chrome',
          'branch': 'release-R90-13816.B',
          'result': 'crr90',
      },
      {
          'cache': 'chromiumos',
          'branch': 'release-R90-13816.B',
          'result': 'crosr90',
      },
      {
          'cache': 'foo',
          'branch': 'stabilize-rust-13836.B',
          'result': 'stabilize',
      },
      {
          'cache': 'chromeosSDK',
          'branch': 'main',
          'result': 'sdk',
      },
  ]
  for test in suffix_test:
    api.assertions.assertEqual(
        test['result'],
        api.gcloud._determine_disk_suffix(cache=test['cache'],
                                          branch=test['branch']))

  compliance_tests = {
      'main': True,
      'release-R90-13816.B': False,
      'main-main-main-main-main-main-main-123456789-123456789-123456789': False
  }
  for test, result in compliance_tests.items():
    call_result = api.gcloud._is_rfc1035_compliant(test)
    api.assertions.assertEqual(result, call_result)

  scrubbing_tests = {
      'main': 'main',
      'release-R90-13816.B': 'release-r90-13816-b',
      'MaIN': 'main',
  }
  for test, result in scrubbing_tests.items():
    new_branch = api.gcloud._scrub_special_characters(test)
    api.assertions.assertEqual(result, new_branch)

  # Assert the default is set via @property.
  api.gcloud.cache_action = SourceCacheAction.MOUNT_SPECIFIC_IMAGE
  api.assertions.assertTrue(
      api.gcloud.cache_action == SourceCacheAction.MOUNT_SPECIFIC_IMAGE)


def GenTests(api):
  yield api.test(
      'basic',
      api.step_data('delete instance', retcode=1),
      api.step_data('delete instance (2)', retcode=1),
      api.post_check(post_process.MustRun, 'delete instance (3)'),
  )
