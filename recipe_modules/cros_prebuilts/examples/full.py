# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'cros_infra_config',
    'cros_prebuilts',
    'test_util',
]

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget, Profile
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.recipe_modules.chromeos.cros_prebuilts.cros_prebuilts import (
    CrosPrebuiltsProperties)
from PB.recipe_modules.chromeos.cros_prebuilts.examples.full import (
    FullProperties)

from recipe_engine.post_process import MustRun, DoesNotRun

PROPERTIES = FullProperties


def RunSteps(api, properties):
  api.cros_infra_config.configure_builder()
  api.cros_prebuilts.get_package_index_info(properties.gs_bucket)
  api.cros_prebuilts.upload_target_prebuilts(properties.build_target,
                                             properties.profile,
                                             BuilderConfig.Id.POSTSUBMIT,
                                             properties.gs_bucket,
                                             properties.private)


def GenTests(api):

  def test_data(private=False, use_staging=False,
                enable_snapshot_prebuilts=True, send_snapshot_prebuilts=4,
                disable_overlay_commits=False, profile=None):
    gs_bucket = 'staging-prebuilt-bucket' if use_staging else 'prebuilt-bucket'
    ret = api.test_util.test_child_build('amd64-generic', cq=False).build
    ret += api.properties(
        FullProperties(
            build_target=BuildTarget(name='target'), private=private,
            gs_bucket=gs_bucket, profile=Profile(name=profile)))

    ret += api.properties(
        **{
            "$chromeos/cros_prebuilts":
                CrosPrebuiltsProperties(
                    use_staging_branch=use_staging,
                    enable_snapshot_prebuilts=enable_snapshot_prebuilts,
                    send_snapshot_prebuilts=send_snapshot_prebuilts,
                    disable_overlay_commits=disable_overlay_commits)
        })

    if not disable_overlay_commits:
      ret += api.post_check(verify_branch,
                            'staging' if use_staging else 'master')
    ret += api.post_check(MustRun if private else DoesNotRun,
                          'upload prebuilts.read gs acls')
    check = MustRun if enable_snapshot_prebuilts else DoesNotRun
    ret += api.post_check(check, 'upload prebuilts.upload metadata')
    ret += api.post_check(check, 'upload prebuilts.upload metadata.gsutil acl')
    check = DoesNotRun if disable_overlay_commits else MustRun
    ret += api.post_check(check, 'upload prebuilts.update binhost conf file')
    return ret

  def verify_branch(check, steps, branch):
    expected = ['git', 'fetch', 'cros', 'refs/heads/{}:'.format(branch)]
    return check(steps['upload prebuilts.update binhost conf file.'
                       'git transaction.git fetch'].cmd == expected)

  for private in False, True:
    for use_staging in False, True:
      for enable_snapshot_prebuilts in False, True:
        for send_snapshot_prebuilts in False, True:
          name = '%s%s%s%s' % (
              'staging-' if use_staging else '',
              'private' if private else 'public',
              '-snapshot' if enable_snapshot_prebuilts else '',
              '-send' if send_snapshot_prebuilts else '',
          )
          yield api.test(
              name,
              test_data(private, use_staging, enable_snapshot_prebuilts,
                        send_snapshot_prebuilts))

  yield api.test('disable-overlay-commits',
                 test_data(disable_overlay_commits=True))

  yield api.test('with-profile', test_data(profile='generic_build'))
