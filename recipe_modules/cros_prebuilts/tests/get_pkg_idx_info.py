# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from collections import namedtuple

from PB.chromiumos.common import BuildTarget, PackageIndexInfo, Profile
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.recipe_modules.chromeos.cros_prebuilts.cros_prebuilts import CrosPrebuiltsProperties
from PB.recipe_modules.chromeos.cros_prebuilts.tests.get_pkg_idx_info import GetPkgIdxInfoProperties
from PB.recipe_modules.chromeos.cros_prebuilts.tests.get_pkg_idx_info import TestDataMap

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_infra_config',
    'cros_prebuilts',
    'test_util',
]


PROPERTIES = GetPkgIdxInfoProperties


def RunSteps(api, properties):
  api.cros_infra_config.configure_builder()

  # There are extra layers in the message for test_data_dict, we need to remove
  # them.  (There is no support for nested maps: the solution is to map string
  # to "message containing a map".
  data = {}
  for snap, snap_val in properties.test_data_dict.snapshots.items():
    data[snap] = {}
    for targ, targ_val in snap_val.targets.items():
      data[snap][targ] = {}
      for p_name, prof_val in targ_val.profiles.items():
        p_name = p_name or 'base'
        data[snap][targ][p_name] = {}
        for fname, info in prof_val.files.items():
          data[snap][targ][p_name][fname] = info

  info = api.cros_prebuilts._get_snapshot_package_index_info(
      [x.id for x in properties.gitiles_commits], properties.build_target,
      properties.profile, properties.gs_bucket, test_data_dict=data)
  api.assertions.assertEqual(list(properties.expected_package_index_info), info)


def GenTests(api):

  def make_snapshots(ids, **kwargs):
    return [GitilesCommit(id=x, **kwargs) for x in ids]

  def make_info(snapshot_sha, snapshot_number, target, pname, location=None):
    location = location or 'gs://bucket/board/%s/KIND-VER-888/packages' % target
    return PackageIndexInfo(snapshot_sha=snapshot_sha,
                            snapshot_number=snapshot_number,
                            build_target=BuildTarget(name=target),
                            profile=Profile(name=pname), location=location)

  _file = namedtuple('_file',
                     ['sha', 'num', 'btname', 'pname', 'fname', 'location'])

  def make_test_data(files):
    data = TestDataMap()
    for f in files:
      item = data.snapshots[f.sha].targets[f.btname].profiles[f.pname].files[
          f.fname]
      item.snapshot_sha = f.sha
      item.snapshot_number = f.num
      item.build_target.name = f.btname
      item.profile.name = f.pname
      item.location = (
          f.location or 'gs://bucket/board/%s/KIND-VER-888/packages' % f.btname)
    return data

  def test_data(use_staging=False, test_data_dict=None,
                send_snapshot_prebuilts=1, snapshots=None, build_target=None,
                profile=None, expected_package_index_info=None):

    expected_package_index_info = expected_package_index_info or []
    gs_bucket = 'staging-prebuilt-bucket' if use_staging else 'prebuilt-bucket'
    snapshots = snapshots or make_snapshots(['111', '333', '222'])
    build_target = (
        build_target if build_target and build_target.name else BuildTarget(
            name='coral'))

    ret = api.test_util.test_child_build('coral', cq=False).build
    ret += api.properties(
        GetPkgIdxInfoProperties(
            gitiles_commits=snapshots, build_target=build_target,
            profile=profile, gs_bucket=gs_bucket, test_data_dict=test_data_dict,
            expected_package_index_info=expected_package_index_info))

    ret += api.properties(
        **{
            '$chromeos/cros_prebuilts':
                CrosPrebuiltsProperties(
                    use_staging_branch=use_staging,
                    send_snapshot_prebuilts=send_snapshot_prebuilts)
        })

    return ret

  yield api.test('disabled', test_data(send_snapshot_prebuilts=0))

  yield api.test('nothing-found', test_data())

  yield api.test(
      'partial-prebuilts',
      test_data(
          build_target=BuildTarget(name='a'),
          snapshots=make_snapshots(['1', '3', '2']),
          profile=Profile(name='prof'), test_data_dict=make_test_data([
              _file('1', 5555, 'a', 'prof', 'a-prof-881-ps.json', ''),
              _file('1', 5555, 'a', 'prof', 'a-prof-asan-882-ps.json', 'other'),
              _file('1', 5555, 'a', 'base', 'a-882-ps.json', 'other'),
              _file('3', 5554, 'a', 'genb', 'a-ut-only-771-ps.json', ''),
          ]), expected_package_index_info=[
              make_info('1', 5555, 'a', 'prof'),
              make_info('1', 5555, 'a', 'prof', 'other'),
          ]))
