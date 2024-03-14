# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests build failure aggregation by reason."""

from PB.chromiumos.common import PackageInfo

from PB.recipe_modules.chromeos.failures.examples.build_failures import BuildProperties
from PB.recipe_modules.chromeos.failures.failures import PackageFailure

from recipe_engine import post_process

from google.protobuf import json_format

DEPS = [
    'recipe_engine/properties',
    'failures',
    'test_util',
]

PROPERTIES = BuildProperties


def RunSteps(api, properties):

  results = api.failures.get_build_results(properties.builds)
  return api.failures.aggregate_failures(results)


def GenTests(api):
  builds = [api.test_util.test_child_build('atlas', status='FAILURE').message]
  yield api.test(
      'no-failure-reason', api.properties(BuildProperties(builds=builds)),
      api.post_check(post_process.ResultReasonRE,
                     '1 out of 1 build failed\n\n'), status='FAILURE')

  builds = [
      api.test_util.test_child_build(
          'atlas', status='FAILURE', output_properties={
              'package_failures': [
                  json_format.MessageToDict(
                      PackageFailure(
                          package=PackageInfo(category='foo',
                                              package_name='bar'),
                          phase='COMPILE'))
              ]
          }).message
  ]
  yield api.test(
      'package-failure', api.properties(BuildProperties(builds=builds)),
      api.post_check(post_process.ResultReasonRE,
                     '1 out of 1 builds failed compilation for foo/bar\n\n'),
      status='FAILURE')

  builds = [
      api.test_util.test_child_build(
          'atlas', status='FAILURE', output_properties={
              'package_failures': [
                  json_format.MessageToDict(
                      PackageFailure(
                          package=PackageInfo(category='foo',
                                              package_name='bar'),
                          phase='COMPILE', affected_by_changes=True))
              ]
          }).message
  ]
  yield api.test(
      'package-failure-affected-by-changes',
      api.properties(BuildProperties(builds=builds)),
      api.post_check(
          post_process.ResultReasonRE,
          r'1 out of 1 builds failed compilation for foo/bar \(affected by changes in CQ run\)\n\n'
      ), status='FAILURE')

  builds = [
      api.test_util.test_child_build(
          'atlas', status='FAILURE', output_properties={
              'package_failures': [
                  json_format.MessageToDict(
                      PackageFailure(
                          package=PackageInfo(category='foo',
                                              package_name='bar'),
                          phase='COMPILE', affected_by_changes=True,
                          snapshot_comparison='MATCHING_FAILURE_FOUND'))
              ]
          }).message
  ]
  yield api.test(
      'package-failure-with-snapshot-comparison',
      api.properties(BuildProperties(builds=builds)),
      api.post_check(
          post_process.ResultReasonRE,
          r'1 out of 1 builds failed compilation for foo/bar \(failure also seen on snapshot builds\)\n\n'
      ), status='FAILURE')

  builds = [
      api.test_util.test_child_build(
          'atlas', status='FAILURE', output_properties={
              'package_failures': [
                  json_format.MessageToDict(
                      PackageFailure(
                          package=PackageInfo(category='foo',
                                              package_name='bar'),
                          phase='COMPILE'))
              ]
          }).message,
      api.test_util.test_child_build('volteer', status='FAILURE').message,
  ]
  yield api.test(
      'build-failure-without-reason-does-not-bubble-up',
      api.properties(BuildProperties(builds=builds)),
      api.post_check(post_process.ResultReasonRE,
                     '2 out of 2 builds failed\n\n'), status='FAILURE')

  builds = [
      api.test_util.test_child_build(
          'atlas', status='FAILURE', output_properties={
              'package_failures': [
                  json_format.MessageToDict(
                      PackageFailure(
                          package=PackageInfo(category='foo',
                                              package_name='bar'),
                          phase='COMPILE'))
              ]
          }).message,
      api.test_util.test_child_build(
          'volteer', status='FAILURE', output_properties={
              'package_failures': [
                  json_format.MessageToDict(
                      PackageFailure(
                          package=PackageInfo(category='foo',
                                              package_name='baz'),
                          phase='COMPILE'))
              ]
          }).message,
  ]
  yield api.test(
      'two-failure-reasons', api.properties(BuildProperties(builds=builds)),
      api.post_check(post_process.ResultReasonRE,
                     '1 out of 2 builds failed compilation for foo/bar\n\n'),
      api.post_check(post_process.ResultReasonRE,
                     '1 out of 2 builds failed compilation for foo/baz\n\n'),
      status='FAILURE')

  builds = [
      api.test_util.test_child_build(
          'atlas', status='FAILURE', output_properties={
              'package_failures': [
                  json_format.MessageToDict(
                      PackageFailure(
                          package=PackageInfo(category='foo',
                                              package_name='bar'),
                          phase='COMPILE'))
              ]
          }).message,
      api.test_util.test_child_build(
          'volteer', status='FAILURE', output_properties={
              'package_failures': [
                  json_format.MessageToDict(
                      PackageFailure(
                          package=PackageInfo(category='foo',
                                              package_name='baz'),
                          phase='COMPILE'))
              ]
          }).message,
      api.test_util.test_child_build('zork', status='FAILURE').message,
  ]
  yield api.test(
      'more-than-2-failure-reasons-does-not-bubble-up',
      api.properties(BuildProperties(builds=builds)),
      api.post_check(post_process.ResultReasonRE,
                     '3 out of 3 builds failed\n\n'), status='FAILURE')
