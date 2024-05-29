# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import json

from PB.chromite.api.image import Image
from PB.chromite.api.packages import GetTargetVersionsResponse
from PB.chromiumos import common as common_pb2
from PB.recipe_modules.chromeos.observability_image_size.tests.publish import PublishTestProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'cros_build_api',
    'cros_infra_config',
    'observability_image_size',
    'test_util',
]


PROPERTIES = PublishTestProperties


def RunSteps(api, properties):
  # add_target_versions.
  milestone = properties.milestone or '100'
  platform_version = properties.platform_version or '12345.6.7'
  full_version = properties.full_version or 'R{}-{}'.format(
      milestone, platform_version)
  target_versions = GetTargetVersionsResponse(
      full_version=full_version,
      milestone_version=milestone,
      platform_version=platform_version,
  )

  # add_builder_metadata.
  name = properties.builder_name or 'amd64-generic-snapshot'
  config = api.cros_infra_config.get_builder_config(name)

  if properties.skip_publish_image_sizes:
    config.general.publish_image_sizes = False
  elif name.endswith('snapshot'):
    config.general.publish_image_sizes = True

  # get_image_size_data.
  build_target = common_pb2.BuildTarget(name='amd64-generic')
  chroot = common_pb2.Chroot()
  images = []
  if common_pb2.IMAGE_TYPE_BASE in properties.image_types:
    images.append(
        Image(path='/tmp/base-image.bin', type=common_pb2.IMAGE_TYPE_BASE,
              build_target=build_target))
  if common_pb2.IMAGE_TYPE_TEST in properties.image_types:
    images.append(
        Image(path='/tmp/test-image.bin', type=common_pb2.IMAGE_TYPE_TEST,
              build_target=build_target))

  api.observability_image_size.publish(config, build_target, target_versions,
                                       images, chroot)


def GenTests(api):

  def test_build(build_target='amd64-generic', **kwargs):
    """Helper for creating build."""
    return api.test_util.test_child_build(build_target, **kwargs).build

  def _partition_data(name, pkgs):
    apparent = 0
    disk_utilization = 0
    for pkg in pkgs:
      apparent += pkg['apparent_size']
      disk_utilization += pkg['disk_utilization_size']
    return {
        'partition_name': name,
        'packages': pkgs,
        'partition_apparent_size': apparent,
        'partition_disk_utilization_size': disk_utilization,
    }

  def _base_image_data(rootfs_pkgs):
    return {
        'image_type': common_pb2.IMAGE_TYPE_BASE,
        'image_partition_data': [_partition_data('rootfs', rootfs_pkgs)]
    }

  def _test_image_data(rootfs_pkgs, stateful_pkgs):
    return {
        'image_type':
            common_pb2.IMAGE_TYPE_TEST,
        'image_partition_data': [
            _partition_data('rootfs', rootfs_pkgs),
            _partition_data('stateful', stateful_pkgs),
        ]
    }

  def image_size_data(rootfs_pkgs, stateful_pkgs=None):
    ret = [_base_image_data(rootfs_pkgs)]
    if stateful_pkgs:
      ret.append(_test_image_data(rootfs_pkgs, stateful_pkgs))
    return json.dumps({'image_data': ret}, sort_keys=True)

  def pkg_data(category, package, major=0, minor=None, patch=None,
               extended=None, revision=0, apparent=0, disk_utilization=0):
    full_components = [
        str(x) for x in [major, minor, patch, extended] if x is not None
    ]
    revision_suffix = '' if not revision else '-r%s' % revision
    return {
        'identifier': {
            'package_name': {
                'atom': '%s/%s' % (category, package),
                'category': category,
                'package': package,
            },
            'package_version': {
                'major':
                    major,
                'minor':
                    minor or 0,
                'patch':
                    patch or 0,
                'extended':
                    extended or 0,
                'revision':
                    revision,
                'full_version':
                    '%s%s' % ('.'.join(full_components), revision_suffix),
            },
        },
        'apparent_size': apparent,
        'disk_utilization_size': disk_utilization,
    }

  def simple_pkg():
    return pkg_data('foo', 'bar', major=1, apparent=1, disk_utilization=4096)

  yield api.test(
      'basic', test_build(),
      api.properties(PublishTestProperties(
          skip_publish_image_sizes=True,
      )), api.properties(image_types=[common_pb2.IMAGE_TYPE_BASE]),
      api.cros_build_api.set_api_return(
          'collect image size data.add data from images',
          'ObservabilityService/GetImageSizeData',
          image_size_data(rootfs_pkgs=[
              pkg_data('cat', 'foo', major=0, minor=0, patch=1, revision=1234,
                       apparent=1, disk_utilization=4096),
              pkg_data('cat', 'bar', major=1, apparent=2,
                       disk_utilization=4096),
              pkg_data('virtual', 'baz', major=2, minor=1),
          ])), api.post_check(post_process.MustRun, 'collect image size data'),
      api.post_check(
          post_process.MustRun,
          'collect image size data.add image size data to output properties'),
      api.post_check(post_process.DoesNotRun,
                     'collect image size data.publish image size data'),
      api.post_check(post_process.StepTextEquals, 'collect image size data',
                     'Skipped: Image size publishing disabled.'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'cq-build', test_build(cq=True),
      api.properties(
          PublishTestProperties(builder_name='amd64-generic-cq',
                                image_types=[common_pb2.IMAGE_TYPE_BASE])),
      api.cros_build_api.set_api_return(
          'collect image size data.add data from images',
          'ObservabilityService/GetImageSizeData',
          image_size_data(rootfs_pkgs=[
              pkg_data('cat', 'foo', major=0, minor=0, patch=1, revision=1234,
                       apparent=1, disk_utilization=4096),
              pkg_data('cat', 'bar', major=1, apparent=2,
                       disk_utilization=4096),
              pkg_data('virtual', 'baz', major=2, minor=1),
          ])), api.post_check(post_process.MustRun, 'collect image size data'),
      api.post_check(
          post_process.MustRun,
          'collect image size data.add image size data to output properties'),
      api.post_check(post_process.DoesNotRun,
                     'collect image size data.publish image size data'),
      api.post_check(post_process.StepTextEquals, 'collect image size data',
                     'Skipped: Image size publishing disabled.'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-data-fails',
      test_build(),
      api.post_check(post_process.StepFailure, 'collect image size data'),
      api.post_check(post_process.ResultReason, 'No images provided.'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'bad-platform-version',
      test_build(),
      api.properties(
          PublishTestProperties(
              image_types=[common_pb2.IMAGE_TYPE_BASE],
              platform_version='1.2',
          )),
      api.post_check(post_process.StepFailure,
                     'collect image size data.add version data'),
      api.post_check(post_process.ResultReason, 'Invalid platform version 1.2'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'valid-platform-version', test_build(),
      api.properties(
          PublishTestProperties(image_types=[common_pb2.IMAGE_TYPE_BASE],
                                milestone='1', platform_version='2.3.4')),
      api.cros_build_api.set_api_return(
          'collect image size data.add data from images',
          'ObservabilityService/GetImageSizeData',
          image_size_data(rootfs_pkgs=[simple_pkg()])),
      api.post_process(post_process.LogContains, 'collect image size data',
                       'image_data.json', [
                           '"milestone": 1',
                           '"platformBuild": 2',
                           '"platformBranch": 3',
                           '"platformPatch": 4',
                       ]), api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-endpoint', test_build(),
      api.properties(image_types=[common_pb2.IMAGE_TYPE_BASE]),
      api.cros_build_api.remove_endpoints([
          'ObservabilityService/GetImageSizeData',
      ]),
      api.post_check(post_process.StepTextEquals, 'collect image size data',
                     'Skipped: Image size data could not be collected.'),
      api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-packages', test_build(),
      api.properties(image_types=[common_pb2.IMAGE_TYPE_BASE]),
      api.cros_build_api.set_api_return(
          'collect image size data.add data from images',
          'ObservabilityService/GetImageSizeData',
          image_size_data(rootfs_pkgs=[])),
      api.post_process(post_process.LogDoesNotContain,
                       'collect image size data', 'image_data.json', [
                           '"apparentSize":',
                           '"diskUtilizationSize":',
                           '"partitionApparentSize":',
                           '"partitionDiskUtilizationSize":',
                       ]), api.post_process(post_process.DropExpectation))

  yield api.test(
      'no-images',
      test_build(),
      api.post_process(post_process.StepFailure, 'collect image size data'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'base-image', test_build(),
      api.properties(image_types=[common_pb2.IMAGE_TYPE_BASE]),
      api.cros_build_api.set_api_return(
          'collect image size data.add data from images',
          'ObservabilityService/GetImageSizeData',
          image_size_data(rootfs_pkgs=[
              pkg_data('cat', 'foo', major=0, minor=0, patch=1, revision=1234,
                       apparent=1, disk_utilization=4096),
              pkg_data('cat', 'bar', major=1, apparent=2,
                       disk_utilization=4096),
              pkg_data('virtual', 'baz', major=2, minor=1),
          ])),
      api.post_process(post_process.LogContains, 'collect image size data',
                       'image_data.json', [
                           '"apparentSize": "1"',
                           '"diskUtilizationSize": "4096"',
                           '"apparentSize": "2"',
                           '"diskUtilizationSize": "4096"',
                           '"partitionApparentSize": "3"',
                           '"partitionDiskUtilizationSize": "8192"',
                       ]), api.post_process(post_process.DropExpectation))

  yield api.test(
      'test-image', test_build(),
      api.properties(image_types=[common_pb2.IMAGE_TYPE_TEST]),
      api.cros_build_api.set_api_return(
          'collect image size data.add data from images',
          'ObservabilityService/GetImageSizeData',
          image_size_data(
              rootfs_pkgs=[
                  pkg_data('cat', 'foo', major=0, minor=0, patch=1,
                           revision=1234, apparent=1, disk_utilization=4096),
                  pkg_data('cat', 'bar', major=1, apparent=1,
                           disk_utilization=4096),
                  pkg_data('virtual', 'baz', major=2, minor=1),
              ], stateful_pkgs=[
                  pkg_data('cat', 'testlib', major=1, minor=2, patch=3,
                           extended=4, revision=5, apparent=1,
                           disk_utilization=4096),
                  pkg_data('cat', 'tests', major=6, apparent=1,
                           disk_utilization=4096),
                  pkg_data('cat', 'othertestlib', major=1, apparent=1,
                           disk_utilization=4096),
              ])),
      api.post_process(post_process.LogContains, 'collect image size data',
                       'image_data.json', [
                           '"partitionApparentSize": "2"',
                           '"partitionDiskUtilizationSize": "8192"',
                           '"partitionApparentSize": "3"',
                           '"partitionDiskUtilizationSize": "12288"',
                       ]), api.post_process(post_process.DropExpectation))
