# -*- codiing: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for quota limits."""

import os
import json
from recipe_engine.post_process import DropExpectation

from PB.recipe_modules.chromeos.auto_runner_util.auto_runner_util import AutoRunnerUtilProperties, HostProjects
from RECIPE_MODULES.chromeos.auto_runner_util.api import EnhancedChangeInfo

DEPS = [
    'recipe_engine/assertions',
    'auto_runner_util',
    'gerrit',
    'recipe_engine/properties',
    'recipe_engine/time',
]


def get_test_output_as_jsonobj(filename: str) -> str:
  with open(
      os.path.join(os.path.abspath(os.path.dirname(__file__)), filename),
      encoding='utf-8') as f:
    return json.load(f)


def RunSteps(api):
  actual = api.auto_runner_util.get_eligible_cls()
  expected = api.properties['expected_changes']
  api.assertions.assertTrue(actual == expected)


def GenTests(api):
  yield api.test(
      'basic_with_exceeding_daily_limit_so_return_only_subset_of_eligibles',
      api.time.seed(1717214400),  #Sun Jun 01 2024 04:00:00 GMT+0000
      api.properties(
          **{
              '$chromeos/auto_runner_util':
                  AutoRunnerUtilProperties(
                      max_limit_per_query=2, host_projects=[
                          HostProjects(host='mychromium',
                                       project_prefix=['mychromiumos']),
                      ], daily_quota=6)
          },
          expected_changes={
              #5590139 has two cq counts by auto runner, so its lower priority
              #hence it does not make the quota cut.
              EnhancedChangeInfo({
                  '_number': 5590140,
                  'project': 'mychromiumos'
              }, 'mychromium-review.googlesource.com', None),
              EnhancedChangeInfo({
                  '_number': 5590141,
                  'project': 'mychromiumos'
              }, 'mychromium-review.googlesource.com', None),
          }),
      api.gerrit.set_gerrit_related_changes(
          {
              'related': [{
                  '_change_number': 5590294,
                  '_revision_number': 1,
                  'host': 'https://mychromium-review.googlesource.com',
                  'project': 'mychromiumos'
              }]
          }, step_name='Querying relation chains'),
      api.gerrit.set_query_changes_response(
          step_name='Looking for CLs in host mychromium.Looking for CLs in project mychromiumos',
          changes=get_test_output_as_jsonobj('test_output.json'),
          host_url='https://mychromium-review.googlesource.com', iteration=1),
      api.gerrit.set_query_changes_response(
          step_name='Calculating quota usage thus far.Looking for CLs in host mychromium.Looking for CLs in project mychromiumos',
          changes=get_test_output_as_jsonobj('test_output.json'),
          host_url='https://mychromium-review.googlesource.com', iteration=1),
      api.post_process(DropExpectation))
  yield api.test(
      'basic_with_exceeding_daily_limit_cutting_by_last_updated',
      api.time.seed(1717214400),  #Sun Jun 01 2024 04:00:00 GMT+0000
      api.properties(
          **{
              '$chromeos/auto_runner_util':
                  AutoRunnerUtilProperties(
                      max_limit_per_query=2, host_projects=[
                          HostProjects(host='mychromium',
                                       project_prefix=['mychromiumos']),
                      ], daily_quota=5, daily_quota_per_cl=2)
          },
          expected_changes={
              #Between 5590140 and 5590141, the later was updated the latest.
              #We want to give priority that was most recently updated.
              EnhancedChangeInfo({
                  '_number': 5590141,
                  'project': 'mychromiumos'
              }, 'mychromium-review.googlesource.com', None),
          }),
      api.gerrit.set_gerrit_related_changes(
          {
              'related': [{
                  '_change_number': 5590294,
                  '_revision_number': 1,
                  'host': 'https://mychromium-review.googlesource.com',
                  'project': 'mychromiumos'
              }]
          }, step_name='Querying relation chains'),
      api.gerrit.set_query_changes_response(
          step_name='Looking for CLs in host mychromium.Looking for CLs in project mychromiumos',
          changes=get_test_output_as_jsonobj('test_output.json'),
          host_url='https://mychromium-review.googlesource.com', iteration=1),
      api.gerrit.set_query_changes_response(
          step_name='Calculating quota usage thus far.Looking for CLs in host mychromium.Looking for CLs in project mychromiumos',
          changes=get_test_output_as_jsonobj('test_output.json'),
          host_url='https://mychromium-review.googlesource.com', iteration=1),
      api.post_process(DropExpectation))
  yield api.test(
      'basic_with_exceeding_daily_quota_per_cl',
      api.time.seed(1717214400),  #Sun Jun 01 2024 04:00:00 GMT+0000
      api.gerrit.set_query_changes_response(
          step_name='Calculating quota usage thus far.Looking for CLs in host mychromium.Looking for CLs in project mychromiumos',
          changes=get_test_output_as_jsonobj('test_output.json'),
          host_url='https://mychromium-review.googlesource.com', iteration=1),
      api.properties(
          **{
              '$chromeos/auto_runner_util':
                  AutoRunnerUtilProperties(
                      max_limit_per_query=2, host_projects=[
                          HostProjects(host='mychromium',
                                       project_prefix=['mychromiumos']),
                      ], daily_quota_per_cl=1)
          }, expected_changes=set()),
      api.post_process(DropExpectation))
  yield api.test(
      'basic_with_exceeding_daily_quota_at_the_beginning',
      api.time.seed(1717214400),  #Sun Jun 01 2024 04:00:00 GMT+0000
      api.gerrit.set_query_changes_response(
          step_name='Calculating quota usage thus far.Looking for CLs in host mychromium.Looking for CLs in project mychromiumos',
          changes=get_test_output_as_jsonobj('test_output.json'),
          host_url='https://mychromium-review.googlesource.com', iteration=1),
      api.properties(
          **{
              '$chromeos/auto_runner_util':
                  AutoRunnerUtilProperties(
                      max_limit_per_query=2, host_projects=[
                          HostProjects(host='mychromium',
                                       project_prefix=['mychromiumos']),
                      ], daily_quota=1)
          }, expected_changes=set()),
      api.post_process(DropExpectation))
