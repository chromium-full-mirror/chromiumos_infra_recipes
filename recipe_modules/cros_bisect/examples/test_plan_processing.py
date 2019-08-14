# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_bisect',
]

from recipe_engine.config import List
from recipe_engine.recipe_api import Property

from PB.chromiumos.common import PackageInfo
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from PB.recipe_modules.chromeos.cros_bisect.cros_bisect import (
    CrosBisectProperties)

from google.protobuf import json_format as jsonpb
from google.protobuf import struct_pb2


def RunSteps(api):
  build1 = build_pb2.Build(
      builder=build_pb2.BuilderID(project='chromeos', bucket='bucket',
                                  builder='foo-builder'),
      status=common_pb2.SUCCESS)
  build2 = build_pb2.Build(
      builder=build_pb2.BuilderID(project='chromeos', bucket='bucket',
                                  builder='bar-builder'),
      status=common_pb2.SUCCESS)
  # Here we set up the completed builds with the properties needed by
  # cros_bisect to do the BuildPayload fix up.
  api.cros_bisect.test_api.add_output_props(
      build=build1,
      build_target_name='foo',
      gs_bucket='bucket1',
      gs_path='path1')
  api.cros_bisect.test_api.add_output_props(
      build=build2,
      build_target_name='bar',
      gs_bucket='bucket2',
      gs_path='path2',
      files_by_artifact={
          'IMAGE_ZIP': ['zeimage.zip'],
          'TAST_FILES': ['zetast.zip'],
          'AUTOTEST_FILES': ['a1.zip', 'a2.zip'],
      })

  # This verifies that:
  # 1) The HwTest which were split out into separate test failures get correctly
  #    regrouped by their TestSuiteCommon.
  # 2) The TestUnitCommon.BuildPayload get correctly updated for current
  #    invocation
  test_plan = api.cros_bisect.get_test_plan([build1, build2])
  api.assertions.assertEqual(len(test_plan.hw_test_units), 2)
  for hw_test_unit in test_plan.hw_test_units:
    if hw_test_unit.common.build_target.name == 'foo':
      api.assertions.assertEqual(len(hw_test_unit.hw_test_cfg.hw_test), 1)
      build_payload = hw_test_unit.common.build_payload
      api.assertions.assertEqual(build_payload.artifacts_gs_bucket, 'bucket1')
      api.assertions.assertEqual(build_payload.artifacts_gs_path, 'path1')
      expected = struct_pb2.Struct()
      expected.get_or_create_list('IMAGE_ZIP').append('image.zip')
      expected.get_or_create_list('TAST_FILES').extend(
          ['tast1.zip', 'tast2.zip'])
      api.assertions.assertEqual(build_payload.files_by_artifact, expected)
    elif hw_test_unit.common.build_target.name == 'bar':
      api.assertions.assertEqual(len(hw_test_unit.hw_test_cfg.hw_test), 2)
      build_payload = hw_test_unit.common.build_payload
      api.assertions.assertEqual(build_payload.artifacts_gs_bucket, 'bucket2')
      api.assertions.assertEqual(build_payload.artifacts_gs_path, 'path2')
      expected = struct_pb2.Struct()
      expected.get_or_create_list('IMAGE_ZIP').append('zeimage.zip')
      expected.get_or_create_list('TAST_FILES').append('zetast.zip')
      expected.get_or_create_list('AUTOTEST_FILES').extend(['a1.zip', 'a2.zip'])
      api.assertions.assertEqual(build_payload.files_by_artifact, expected)
    else: # pragma: no cover
      api.assertions.fail('Expected to find build_target name foo or bar.')

def GenTests(api):
  hw_test_unit1 = api.cros_bisect.hw_test_unit('foo')
  hw_test_unit2 = api.cros_bisect.hw_test_unit('bar')
  hw_test_unit3 = api.cros_bisect.hw_test_unit('bar')

  yield (api.test('with-test-plan') +  #
         api.properties(
             **{'$chromeos/cros_bisect':
                CrosBisectProperties(test={'hw_test_failures': [
                    CrosBisectProperties.TestFailures.TestFailure(
                        test_spec=jsonpb.MessageToJson(hw_test_unit1)),
                    CrosBisectProperties.TestFailures.TestFailure(
                        test_spec=jsonpb.MessageToJson(hw_test_unit2)),
                    CrosBisectProperties.TestFailures.TestFailure(
                        test_spec=jsonpb.MessageToJson(hw_test_unit3)),
                ]})}
         ))
