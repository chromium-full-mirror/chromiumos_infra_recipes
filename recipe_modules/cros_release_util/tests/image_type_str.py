# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Testing for cros_release_util.image_type_to_str."""

from recipe_engine import post_process

from PB.chromiumos import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_release_util',
]



def RunSteps(api):
  image_type = api.properties.thaw()['image_type']
  expected_image_type_str = api.properties.thaw()['expected_image_type_str']
  image_type_str = api.cros_release_util.image_type_to_str(image_type)
  api.assertions.assertEqual(expected_image_type_str, image_type_str)


def GenTests(api):
  yield api.test(
      'base',
      api.properties(image_type=common_pb2.IMAGE_TYPE_BASE,
                     expected_image_type_str='base'),
      api.post_process(post_process.DropExpectation))
  yield api.test(
      'accessory_rwsig',
      api.properties(image_type=common_pb2.IMAGE_TYPE_ACCESSORY_RWSIG,
                     expected_image_type_str='accessory_rwsig'),
      api.post_process(post_process.DropExpectation))
  yield api.test(
      'recovery',
      api.properties(image_type=common_pb2.IMAGE_TYPE_RECOVERY,
                     expected_image_type_str='recovery'),
      api.post_process(post_process.DropExpectation))
