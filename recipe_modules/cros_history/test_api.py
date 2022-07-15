# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto \
  import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from google.protobuf import timestamp_pb2

COMPRESSED_UPREV_RESPONSE = """
eJzVmEGL00AUx5mLlldF6UXJTVBRcDpNm7bx0yzTZNrMbtIJM5PWXgVB8LDqiqJ4EBQ8i+LnM93t\n
TGLdYJF1k57mJX0z/XXmvTf/VzhB8BKRCVFkSbgkT/JBsoCn7CCIGZ1nKQkiKRKeJUIdLIU8UikN\n
GFEyIKnkC6oZFgsmY7pSZGPghCstaYw3DmcrMKHwhCpGaIqpmEVmxL1ur+ti6fZ9b9hlk4zHIXxF\n
8OWiqFIpDlmg8UzE4ZTPZ0xWgCX6CNM0w1MukyWVf76wqF7/ce2ki23SxV9IfyL4ftGkh0znR81o\n
UnXWmRaaqbLj+lFVfmDBfdcGww8E3xoAHvPJudzr9wbbG4zHBvsNgleXjh1oLubKjAZr6Hojg/UR\n
wftLx0rxkksWM6XKtt21UZH5nxF8qgEv0jpVWDGZz91+NpiDns2ltwhOaqDk86mk1rDb5/o26F4j\n
OK4BbM70ZiigXL/mkFMsyCTXq7Jt8byivnxA8K4GvJCy5DRXrXkKN8By3Ov3DdwLBM//EU5HXIYH\n
KZX5FhROhpWoVc4ihCYhS3UURFTOWNm2Ye/1BobmGYKn/4cmZAucaR6TKAy0ELGyRnGXFUWsUarF\n
q10L7Kpa/NpJd1Ut/r6qFm8/Vcuomapl2GzV4u2FavGbqlpGTVQt42arFq/JqsVtlGrpN0S1mCLm\n
3IerG/nQuf7bxjrXyn+COF24uX2Jb09olxp847/Y1X8Et6tussp5eT/uDOFWxU1SNW3dDzv38p99\n
Vtmr3Nb9qfMQ2qUqW7li3is6j+DGVrXbdoeiZ8u3vWWKT+WqeQvl3IUrZ9Wg2sv1N5gmMytd8/7C\n
eQBQpMm5nhuxn391uxTDnZaJcrveWoQ7d6BlwqvTMqFXOlpv9AupQxeD\n
"""


class CrosHistoryTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the cros_history module."""

  @recipe_test_api.mod_test_data
  @staticmethod
  def is_retry(value):
    """Return value for is_retry when testing."""
    return value

  def build_with_passed_tests(self, tests, build_id=123,
                              create_time=1562475240):
    """Generate a test build with the 'passed_tests' property.

    Args:
      tests (list[str]): List of tests names that passed.
      build_id (int): The id for the build.
      create_time (int): The create_time for the build in seconds.

    Returns:
      Build: Containing the expected 'passed_tests' and 'test_summary' output
        property.
    """
    build = build_pb2.Build(
        id=build_id,
        builder=builder_common_pb2.BuilderID(builder='cq-orchestrator'),
        create_time=timestamp_pb2.Timestamp(seconds=create_time),
        start_time=timestamp_pb2.Timestamp(seconds=create_time + 1),
        end_time=timestamp_pb2.Timestamp(seconds=create_time + 2),
        status=common_pb2.SUCCESS)
    build.output.properties.update({'passed_tests': tests})
    build.output.properties.update({
        'test_summary': [{
            'name': test,
            'status': 'SUCCESS',
            'critical': True
        } for test in tests]
    })
    build.input.gerrit_changes.extend([common_pb2.GerritChange(change=1234)])
    return build

  def build_with_failed_tests(self, builder_names, build_id=123,
                              create_time=1562475240):
    """Generate a test build with the failed tests in the output.

    Args:
      tests (list[str]): List of builder names that failed hw testing.
      build_id (int): The id for the build.
      create_time (int): The create_time for the build in seconds.

    Returns:
      Build: Containing the expected 'test_failures' and 'test_summary'
        property.
    """
    build = build_pb2.Build(
        id=build_id,
        builder=builder_common_pb2.BuilderID(builder='cq-orchestrator'),
        create_time=timestamp_pb2.Timestamp(seconds=create_time),
        start_time=timestamp_pb2.Timestamp(seconds=create_time + 1),
        end_time=timestamp_pb2.Timestamp(seconds=create_time + 2),
        status=common_pb2.FAILURE)

    build.output.properties.update({
        'test_summary': [{
            'name': '%s.type.suite' % builder_name,
            'status': 'FAILURE',
            'critical': True
        } for builder_name in builder_names]
    })

    build.input.gerrit_changes.extend([common_pb2.GerritChange(change=1234)])
    return build

  def build_with_uprev_response(self):
    """Generate a test build with the uprev response in the output.

    Returns:
      Build: Containing the expected 'compressed_uprev_response' property.
    """
    build = build_pb2.Build(
        id=123, builder=builder_common_pb2.BuilderID(builder='Annealing'))
    build.output.properties.update(
        {'compressed_uprev_response': COMPRESSED_UPREV_RESPONSE})
    return build
