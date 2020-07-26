# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'cros_prebuilts',
]

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.recipe_modules.chromeos.cros_prebuilts.cros_prebuilts import (
    CrosPrebuiltsProperties)
from PB.recipe_modules.chromeos.cros_prebuilts.examples.full import (
    FullProperties)

from recipe_engine import post_process

PROPERTIES = FullProperties


def RunSteps(api, properties):
  api.cros_prebuilts.upload_target_prebuilts(properties.build_target,
                                             BuilderConfig.Id.POSTSUBMIT,
                                             properties.gs_bucket,
                                             properties.private)


def GenTests(api):

  def test_data(private=False, use_staging=False):
    gs_bucket = 'staging-prebuilt-bucket' if use_staging else 'prebuilt-bucket'
    ret = api.properties(
        FullProperties(
            build_target=BuildTarget(name='target'), private=private,
            gs_bucket=gs_bucket))

    if use_staging:
      ret += api.properties(
          **{
              "$chromeos/cros_prebuilts":
                  CrosPrebuiltsProperties(use_staging_branch=True)
          })

    ret += api.post_check(verify_branch, 'staging' if use_staging else 'master')
    ret += api.post_check(
        post_process.MustRun if private else post_process.DoesNotRun,
        'upload prebuilts.read gs acls')
    return ret

  def verify_branch(check, steps, branch):
    expected = ['git', 'fetch', 'cros', 'refs/heads/{}:'.format(branch)]
    return check(steps['upload prebuilts.update binhost conf file.'
                       'git transaction.git fetch'].cmd == expected)

  yield api.test('public', test_data())

  yield api.test('private', test_data(private=True))

  yield api.test('staging-public', test_data(use_staging=True))

  yield api.test('staging-private', test_data(private=True, use_staging=True))
