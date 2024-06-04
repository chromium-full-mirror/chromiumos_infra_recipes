# -*- codiing: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for get_eligible_cls function."""

import os
import json
from recipe_engine import post_process
from recipe_engine.post_process import DropExpectation, MustRun, MustRunRE, DoesNotRun

from PB.recipe_modules.chromeos.auto_runner_util.auto_runner_util import AutoRunnerUtilProperties, HostProjects, CLSignalEnum
from RECIPE_MODULES.chromeos.auto_runner_util.api import EnhancedChangeInfo

DEPS = [
    'recipe_engine/assertions',
    'auto_runner_util',
    'gerrit',
    'recipe_engine/properties',
]


def get_test_output_as_jsonobj(filename: str) -> str:
  with open(
      os.path.join(os.path.abspath(os.path.dirname(__file__)), filename),
      encoding='utf-8') as f:
    return json.load(f)


def RunSteps(api):
  actual = api.auto_runner_util.get_eligible_cls()
  if api.properties['dont_assert']:
    return
  expected = api.properties['expected_changes']
  api.assertions.assertTrue(actual == expected)



def GenTests(api):
  yield api.test(
      'basic', api.properties(dont_assert=True),
      api.post_process(MustRunRE, r'Looking for CLs in host .*'),
      api.post_process(MustRun, 'Filtering CLs that have cq-depends'),
      api.post_process(MustRun, 'Filtering CLs that are in relation chain'),
      api.post_process(MustRun, 'Filtering CLs that do not have any reviewers'),
      api.post_process(DropExpectation))
  yield api.test(
      'basic_with_props',
      api.properties(
          **{
              '$chromeos/auto_runner_util':
                  AutoRunnerUtilProperties(
                      max_limit_per_query=2, host_projects=[
                          HostProjects(host='mychromium',
                                       project_prefix=['mychromiumos']),
                      ], cls_signal=CLSignalEnum.PATCHSET_UPLOAD)
          }, expected_changes={
              EnhancedChangeInfo({
                  '_number': 5590139,
                  'project': 'mychromiumos'
              }, 'mychromium-review.googlesource.com', None),
              EnhancedChangeInfo({
                  '_number': 5590140,
                  'project': 'mychromiumos'
              }, 'mychromium-review.googlesource.com', None),
              EnhancedChangeInfo({
                  '_number': 5590141,
                  'project': 'mychromiumos'
              }, 'mychromium-review.googlesource.com', None),
              EnhancedChangeInfo({
                  '_number': 5590242,
                  'project': 'mychromiumos'
              }, 'mychromium-review.googlesource.com', None)
          },
          dont_assert=False),
      api.gerrit.set_query_changes_response(
          step_name='Looking for CLs in host mychromium.Looking for CLs in project mychromiumos',
          changes=get_test_output_as_jsonobj('test_output.json'),
          host_url='https://mychromium-review.googlesource.com'),
      api.gerrit.set_gerrit_related_changes(
          {
              'related': [{
                  '_change_number': 5590294,
                  '_revision_number': 1,
                  'host': 'https://mychromium-review.googlesource.com',
                  'project': 'mychromiumos'
              }]
          }, step_name='Querying relation chains'),
      api.post_process(
          MustRun,
          'Looking for CLs in host mychromium.Looking for CLs in project mychromiumos'
      ),
      api.post_process(
          post_process.StepCommandContains,
          'Looking for CLs in host mychromium.Looking for CLs in project mychromiumos.'\
            'query https://mychromium-review.googlesource.com.gerrit changes',
          [
              '--limit', '2', '-p', 'status=open', '-p', 'branch=main', '-p',
              'label=Bot-Commit<1', '-p', 'label=Commit-Queue<=0', '-p',
              'label=Code-Review>=0', '-p', 'label=verified>=0', '-p',
              '-is=wip', '-p', '-age=1d', '-p', 'projects=mychromiumos', '-o',
              'CURRENT_REVISION', '-o', 'COMMIT_FOOTERS', '-o',
              'REVIEWER_UPDATES', '-o', 'DETAILED_ACCOUNTS', '-o', 'MESSAGES'
          ]),
      api.post_process(DoesNotRun,
                       'Filtering CLs that do not have any reviewers'),
   api.post_process(DropExpectation))
  yield api.test(
      'basic_with_props_no_reviewers_signal',
      api.properties(
          **{
              '$chromeos/auto_runner_util':
                  AutoRunnerUtilProperties(
                      max_limit_per_query=2, host_projects=[
                          HostProjects(host='mychromium',
                                       project_prefix=['mychromiumos']),
                      ])
          }, expected_changes={
              EnhancedChangeInfo({
                  '_number': 5590139,
                  'project': 'mychromiumos'
              }, 'mychromium-review.googlesource.com', None),
              EnhancedChangeInfo({
                  '_number': 5590140,
                  'project': 'mychromiumos'
              }, 'mychromium-review.googlesource.com', None),
              EnhancedChangeInfo({
                  '_number': 5590141,
                  'project': 'mychromiumos'
              }, 'mychromium-review.googlesource.com', None),
          },
          dont_assert=False),
      api.gerrit.set_query_changes_response(
          step_name='Looking for CLs in host mychromium.Looking for CLs in project mychromiumos',
          changes=get_test_output_as_jsonobj('test_output.json'),
          host_url='https://mychromium-review.googlesource.com'),
      api.gerrit.set_gerrit_related_changes(
          {
              'related': [{
                  '_change_number': 5590294,
                  '_revision_number': 1,
                  'host': 'https://mychromium-review.googlesource.com',
                  'project': 'mychromiumos'
              }]
          }, step_name='Querying relation chains'),
      api.post_process(
          MustRun,
          'Looking for CLs in host mychromium.Looking for CLs in project mychromiumos'
      ),
      api.post_process(
          post_process.StepCommandContains,
          'Looking for CLs in host mychromium.Looking for CLs in project mychromiumos.'\
            'query https://mychromium-review.googlesource.com.gerrit changes',
          [
              '--limit', '2', '-p', 'status=open', '-p', 'branch=main', '-p',
              'label=Bot-Commit<1', '-p', 'label=Commit-Queue<=0', '-p',
              'label=Code-Review>=0', '-p', 'label=verified>=0', '-p',
              '-is=wip', '-p', '-age=1d', '-p', 'projects=mychromiumos', '-o',
              'CURRENT_REVISION', '-o', 'COMMIT_FOOTERS', '-o',
              'REVIEWER_UPDATES', '-o', 'DETAILED_ACCOUNTS', '-o', 'MESSAGES'
          ]),
      api.post_process(MustRun,
                       'Filtering CLs that do not have any reviewers'),
   api.post_process(DropExpectation))
