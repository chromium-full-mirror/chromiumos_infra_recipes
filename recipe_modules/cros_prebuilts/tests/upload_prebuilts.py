# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget, Profile
from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api
from recipe_engine.recipe_api import Property

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_prebuilts',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = {
    'upload_target_prebuilts':
        Property(default=False, kind=bool,
                 help='Whether to upload build target prebuilts.'),
    'upload_devinstall_prebuilts':
        Property(default=False, kind=bool,
                 help='Whether to upload devinstall prebuilts.'),
    'upload_chrome_prebuilts':
        Property(default=False, kind=bool,
                 help='Whether to upload Chrome prebuilts.'),
    'private':
        Property(default=False, kind=bool,
                 help='Whether to upload using private ACLs.'),
    'gs_bucket':
        Property(default='test_bucket', kind=str,
                 help='GS bucket used for uploads.'),
}


def RunSteps(api: recipe_api.RecipeApi, upload_target_prebuilts: bool,
             upload_devinstall_prebuilts: bool, upload_chrome_prebuilts: bool,
             private: bool, gs_bucket: str) -> None:
  target = BuildTarget(name='amd64-generic')
  sysroot = Sysroot(build_target=target)
  builder_config = BuilderConfig.Id.POSTSUBMIT

  if upload_target_prebuilts:
    api.cros_prebuilts.upload_target_prebuilts(target, sysroot, Profile(),
                                               builder_config, gs_bucket,
                                               private)
  if upload_devinstall_prebuilts:
    api.cros_prebuilts.upload_devinstall_prebuilts(target, sysroot, gs_bucket)
  if upload_chrome_prebuilts:
    api.cros_prebuilts.upload_chrome_prebuilts(target, sysroot, builder_config,
                                               gs_bucket, private)


def GenTests(api: recipe_test_api.RecipeTestApi):
  yield api.test(
      'upload-target-prebuilts',
      api.properties(upload_target_prebuilts=True),
      api.post_check(post_process.MustRun, 'upload prebuilts'),
      api.post_check(post_process.DoesNotRun, 'upload prebuilts.read gs acls'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-devinstall-prebuilts',
      api.properties(upload_devinstall_prebuilts=True),
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
      api.properties(upload_chrome_prebuilts=True),
      api.post_check(post_process.MustRun, 'upload chrome prebuilts'),
      api.post_check(post_process.DoesNotRun,
                     'upload chrome prebuilts.read gs acls'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'upload-chrome-prebuilts-private-acls',
      api.properties(upload_chrome_prebuilts=True, private=True),
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
