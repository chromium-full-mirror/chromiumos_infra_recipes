# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_infra_config',
    'cros_prebuilts',
    'git',
    'src_state',
    'test_util',
]

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget, Profile
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
# TODO(crbug/1179353): Remove once public builders are rolled out.
from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import (
    CrosInfraConfigProperties)
from PB.recipe_modules.chromeos.cros_prebuilts.cros_prebuilts import (
    CrosPrebuiltsProperties)
from PB.recipe_modules.chromeos.cros_source.cros_source import (
    CrosSourceProperties)
from PB.recipe_modules.chromeos.cros_prebuilts.examples.full import (
    FullProperties)

from recipe_engine.post_process import MustRun, DoesNotRun

PROPERTIES = FullProperties


def RunSteps(api, properties):
  api.cros_infra_config.configure_builder()

  api.assertions.assertEqual(
      list(properties.expected_package_indexes),
      api.cros_prebuilts.get_package_index_info(properties.gs_bucket,
                                                profile=properties.profile))

  api.cros_prebuilts.upload_target_prebuilts(properties.build_target,
                                             properties.profile,
                                             BuilderConfig.Id.POSTSUBMIT,
                                             properties.gs_bucket,
                                             properties.private)


def GenTests(api):

  def make_package_indexes(gs_bucket, target, profile=None, count=4):
    profile = profile or Profile()
    p_name = profile.name or 'base'
    shas = api.git.generate_test_ids(count=count)
    data_dict = api.cros_prebuilts.generate_snapshot_test_data_dict(
        shas, BuildTarget(name=target), profile, gs_bucket)
    expected_package_indexes = []
    for sha in shas[:4]:
      expected_package_indexes.extend(data_dict[sha][target][p_name].values())
    return expected_package_indexes

  # TODO(crbug/1179353): Remove switch_to_manifest after public builder rollout.
  def test_data(private=False, use_staging=False,
                enable_snapshot_prebuilts=True, send_snapshot_prebuilts=4,
                disable_overlay_commits=False, profile=None,
                expected_package_indexes=None, dirty_source=False,
                switch_to_external_manifest=False):
    gs_bucket = 'staging-prebuilt-bucket' if use_staging else 'prebuilt-bucket'
    target = 'amd64-generic'

    non_base_profile = (profile and profile.name and profile.name != 'base')
    expect_commit = not (disable_overlay_commits or non_base_profile or
                         dirty_source)

    if expected_package_indexes is None:
      count = send_snapshot_prebuilts
      # TODO(crbug/1179353): Remove once public builders are rolled out.
      if (send_snapshot_prebuilts and not private and
          switch_to_external_manifest):
        count = 1
      expected_package_indexes = make_package_indexes(gs_bucket, target,
                                                      profile=profile,
                                                      count=count)

    ret = api.test_util.test_child_build(target, cq=False).build
    test_props = FullProperties(
        build_target=BuildTarget(name=target), private=private,
        gs_bucket=gs_bucket, profile=profile, dirty_source=dirty_source)
    for x in expected_package_indexes:
      test_props.expected_package_indexes.add().CopyFrom(x)

    ret += api.properties(test_props)

    props = {
        '$chromeos/cros_prebuilts':
            CrosPrebuiltsProperties(
                use_staging_branch=use_staging,
                enable_snapshot_prebuilts=enable_snapshot_prebuilts,
                send_snapshot_prebuilts=send_snapshot_prebuilts,
                disable_overlay_commits=disable_overlay_commits)
    }

    # Forcing cros_source to claim dirty source.
    if dirty_source:
      props['$chromeos/cros_source'] = CrosSourceProperties(
          snapshot_cas=CrosSourceProperties.SnapshotCas(digest='xxx'))

    # TODO(crbug/1179353): Remove once public builders are rolled out.
    if switch_to_external_manifest:
      props['$chromeos/cros_infra_config'] = CrosInfraConfigProperties(
          switch_to_external_manifest=True)
    ret += api.properties(**props)

    ret += api.post_check(
        MustRun if private and not dirty_source else DoesNotRun,
        'upload prebuilts.read gs acls')
    check = (
        MustRun
        if enable_snapshot_prebuilts and not dirty_source else DoesNotRun)
    ret += api.post_check(check, 'upload prebuilts.upload metadata')
    ret += api.post_check(check, 'upload prebuilts.upload metadata.gsutil acl')
    check = MustRun if expect_commit else DoesNotRun
    ret += api.post_check(check, 'upload prebuilts.update binhost conf file')
    if expect_commit:
      ret += api.step_data(
          'upload prebuilts.update binhost conf file.'
          'git transaction.diff check.git diff', retcode=1)
      ret += api.post_check(
          verify_branch,
          'staging' if use_staging else api.src_state.default_branch)
    return ret

  def verify_branch(check, steps, branch):
    expected = [
        'git', 'push', '--porcelain', 'cros',
        'HEAD:refs/for/refs/heads/{}%notify=NONE,submit'.format(branch)
    ]
    return check(steps[
        'upload prebuilts.update binhost conf file.git transaction.git push']
                 .cmd == expected)

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

  yield api.test('with-profile',
                 test_data(profile=Profile(name='generic_build')))

  # This test forces dirty source and thus tests the code path of
  # upload_target_prebuilts skipping binhost commit and metadata
  # upload.
  yield api.test('dirty-source', test_data(dirty_source=True))

  # TODO(crbug/1179353): Remove once public builders are rolled out.
  yield api.test('switch-to-external',
                 test_data(switch_to_external_manifest=True))
