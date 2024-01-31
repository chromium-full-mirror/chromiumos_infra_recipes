# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import json

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget, Chroot, Profile
from PB.recipe_modules.chromeos.cros_prebuilts.tests.upload_prebuilts import \
  UploadPrebuiltsProperties
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api

DEPS = [
    'binhost_lookup_service',
    'cros_build_api',
    'cros_prebuilts',
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/properties',
]


PROPERTIES = UploadPrebuiltsProperties


def RunSteps(api: recipe_api.RecipeApi, properties) -> None:

  target = BuildTarget(name='amd64-generic')
  sysroot = Sysroot(build_target=target)
  chroot = Chroot(path='/path/to/chroot', out_path='/path/to/out')
  builder_config = BuilderConfig.Id.POSTSUBMIT

  if properties.upload_target_prebuilts:
    api.cros_prebuilts.upload_target_prebuilts(
        target,
        sysroot,
        chroot,
        properties.profile,
        builder_config,
        properties.gs_bucket,
        properties.private,
    )
  if properties.upload_devinstall_prebuilts:
    api.cros_prebuilts.upload_devinstall_prebuilts(target, sysroot, chroot,
                                                   properties.gs_bucket)
  if properties.upload_chrome_prebuilts:
    api.cros_prebuilts.upload_chrome_prebuilts(target, sysroot, chroot,
                                               properties.profile,
                                               builder_config,
                                               properties.gs_bucket,
                                               properties.private)

  if properties.upload_host_prebuilts:
    api.cros_prebuilts.upload_host_prebuilts(target, chroot, builder_config,
                                             properties.gs_bucket)


def GenTests(api: recipe_test_api.RecipeTestApi):
  yield api.test(
      'upload-target-prebuilts',
      api.properties(upload_target_prebuilts=True, gs_bucket='test_bucket'),
      api.post_check(post_process.MustRun, 'upload prebuilts'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts.read gs acls'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-target-prebuilts-with-profile',
      api.properties(upload_target_prebuilts=True, gs_bucket='test_bucket',
                     profile=Profile(name='some_profile')),
      # A profile is not supported yet on target prebuilts.
      api.post_check(
          post_process.PropertyEquals, 'prebuilts_uri',
          'gs://test_bucket/board/amd64-generic/postsubmit-R99-1234.56.0-101-led_fake-task-id/packages'
      ),
      api.post_check(post_process.MustRun, 'upload prebuilts'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts.read gs acls'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-target-prebuilts-without-profile',
      api.properties(upload_target_prebuilts=True, gs_bucket='test_bucket',
                     profile=Profile()),
      # A profile is not supported yet on target prebuilts.
      api.post_check(
          post_process.PropertyEquals, 'prebuilts_uri',
          'gs://test_bucket/board/amd64-generic/postsubmit-R99-1234.56.0-101-led_fake-task-id/packages'
      ),
      api.post_check(post_process.MustRun, 'upload prebuilts'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts.read gs acls'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-target-prebuilts-no-acls',
      api.properties(upload_target_prebuilts=True, gs_bucket='test_bucket',
                     private=True),
      api.cros_build_api.set_api_return(
          'upload prebuilts', 'BinhostService/GetPrivatePrebuiltAclArgs',
          json.dumps({'args': []}), step_name='read gs acls'),
      api.post_check(post_process.MustRun, 'upload prebuilts'),
      api.post_check(post_process.DoesNotRun,
                     'upload prebuilts.get binhosts.call'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-chrome-prebuilts-no-acls',
      api.properties(upload_chrome_prebuilts=True, gs_bucket='test_bucket',
                     private=True),
      api.cros_build_api.set_api_return(
          'upload chrome prebuilts', 'BinhostService/GetPrivatePrebuiltAclArgs',
          json.dumps({'args': []}), step_name='read gs acls'),
      api.post_check(post_process.MustRun, 'upload chrome prebuilts'),
      api.post_check(post_process.DoesNotRun,
                     'upload chrome prebuilts.get binhosts.call'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-devinstall-prebuilts',
      api.properties(upload_devinstall_prebuilts=True, gs_bucket='test_bucket'),
      api.post_check(post_process.MustRun, 'upload devinstall prebuilts'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts.read gs acls'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-devinstall-prebuilts-no-gs-bucket',
      api.properties(upload_devinstall_prebuilts=True, gs_bucket=None),
      api.post_check(post_process.StepTextEquals, 'upload devinstall prebuilts',
                     'no bucket specified, skipping'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-chrome-prebuilts',
      api.properties(upload_chrome_prebuilts=True, gs_bucket='test_bucket'),
      api.post_check(post_process.MustRun, 'upload chrome prebuilts'),
      api.post_check(post_process.DoesNotRun,
                     'upload chrome prebuilts.read gs acls'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-chrome-prebuilts-with-profile',
      api.properties(upload_chrome_prebuilts=True, gs_bucket='test_bucket',
                     profile=Profile(name='some_profile')),
      api.post_check(post_process.MustRun, 'upload chrome prebuilts'),
      api.post_check(post_process.DoesNotRun,
                     'upload chrome prebuilts.read gs acls'),
      # URI should contain the profile suffix.
      api.post_check(
          post_process.PropertyEquals, 'prebuilts_uri',
          'gs://test_bucket/board/amd64-generic-some_profile/postsubmit-R99-1234.56.0-101-led_fake-task-id/packages'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-chrome-prebuilts-with-base-profile',
      api.properties(upload_chrome_prebuilts=True, gs_bucket='test_bucket',
                     profile=Profile(name='base')),
      api.post_check(post_process.MustRun, 'upload chrome prebuilts'),
      api.post_check(post_process.DoesNotRun,
                     'upload chrome prebuilts.read gs acls'),
      # URI should not contain the profile suffix.
      api.post_check(
          post_process.PropertyEquals, 'prebuilts_uri',
          'gs://test_bucket/board/amd64-generic/postsubmit-R99-1234.56.0-101-led_fake-task-id/packages'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-chrome-prebuilts-without-profile',
      api.properties(upload_chrome_prebuilts=True, gs_bucket='test_bucket',
                     profile=Profile(name='')),
      api.post_check(post_process.MustRun, 'upload chrome prebuilts'),
      api.post_check(post_process.DoesNotRun,
                     'upload chrome prebuilts.read gs acls'),
      # URI should not contain the profile suffix.
      api.post_check(
          post_process.PropertyEquals, 'prebuilts_uri',
          'gs://test_bucket/board/amd64-generic/postsubmit-R99-1234.56.0-101-led_fake-task-id/packages'
      ),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-chrome-prebuilts-private-acls',
      api.properties(upload_chrome_prebuilts=True, gs_bucket='test_bucket',
                     private=True),
      api.post_check(post_process.MustRun,
                     'upload chrome prebuilts.read gs acls'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-chrome-prebuilts-no-gs-bucket',
      api.properties(upload_chrome_prebuilts=True, private=True,
                     gs_bucket=None),
      api.post_check(post_process.StepException, 'upload chrome prebuilts'),
      api.post_check(post_process.SummaryMarkdownRE,
                     'A gs bucket was not specified .*'),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-host-prebuilts',
      api.properties(upload_host_prebuilts=True, gs_bucket='test_bucket'),
      api.post_check(post_process.MustRun, 'upload host prebuilts'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-host-prebuilts-no-gs-bucket',
      api.properties(upload_host_prebuilts=True, gs_bucket=None),
      api.post_check(post_process.StepFailure, 'upload host prebuilts'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  # Binhost metadata is published to the binhost lookup service.
  yield api.test(
      'publish-binhost-metadata',
      api.properties(
          upload_target_prebuilts=True,
          gs_bucket='test_bucket',
          **api.binhost_lookup_service.input_properties,
      ),
      api.buildbucket.generic_build(
          experiments=['chromeos.publish.to.binhost_lookup_service']),
      api.post_check(post_process.StepSuccess,
                     'upload prebuilts.publish binhost metadata'),
      api.post_process(post_process.DropExpectation))

  # Binhost metadata is not published when the
  # `chromeos.publish.to.binhost_lookup_service` experiment is not enabled.
  yield api.test(
      'publish-binhost-metadata-does-not-run',
      api.properties(
          upload_target_prebuilts=True,
          gs_bucket='test_bucket',
          **api.binhost_lookup_service.input_properties,
      ),
      api.post_check(post_process.DoesNotRun,
                     'upload prebuilts.publish binhost metadata'),
      api.post_process(post_process.DropExpectation))
