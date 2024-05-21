# -*- codiing: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the filter_related_changes function."""

from recipe_engine.post_process import (DoesNotRun, DropExpectation)
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'gerrit',
    'auto_runner_util',
]


def is_equal(actual, expected):
  actual_set = set((gc.host, gc.change, gc.project) for gc in actual)
  expected_set = set(
      (gc['host'], gc['change'], gc['project']) for gc in expected)
  return actual_set == expected_set


def convert_frozen_dict_to_gerrit(all_gerrit_changes):
  return [
      GerritChange(host=gc['host'], change=gc['change'], project=gc['project'])
      for gc in all_gerrit_changes
  ]


def RunSteps(api):
  all_fr_gerrit_changes = api.properties['all_gerrit_changes']
  all_gerrit_changes = convert_frozen_dict_to_gerrit(all_fr_gerrit_changes)
  actual = api.auto_runner_util.filter_related_changes(all_gerrit_changes)
  expected = api.properties['filtered_changes']
  expected = api.properties['filtered_changes']
  api.assertions.assertTrue(is_equal(actual, expected))


def GenTests(api):
  yield api.test(
      '''Test for some related change_infos. It should filter related change_infos.'''
      'basic',
      api.properties(
          all_gerrit_changes=[
              {
                  'host': 'chromium-review.googlesource.com',
                  'change': 1234,
                  'patchset': 1,
                  'project': 'myproject'
              },
              {
                  'host': 'chromium-review.googlesource.com',
                  'change': 456,
                  'patchset': 1,
                  'project': 'myproject'
              },
              {
                  'host': 'chromium-review.googlesource.com',
                  'change': 789,
                  'patchset': 1,
                  'project': 'myproject'
              },
          ], filtered_changes=[
              {
                  'host': 'chromium-review.googlesource.com',
                  'change': 1234,
                  'patchset': 1,
                  'project': 'myproject'
              },
              {
                  'host': 'chromium-review.googlesource.com',
                  'change': 789,
                  'patchset': 1,
                  'project': 'myproject'
              },
          ]),
      api.gerrit.set_gerrit_related_changes(
          {
              'related': [{
                  '_change_number': 456,
                  '_revision_number': 1,
                  'host': 'chromium-review.googlesource.com',
                  'project': 'myproject'
              },]
          }, step_name='Filtering Related Chain CLs'),
      api.post_process(DropExpectation))
  yield api.test(
      '''Test for no related changes. It should not filter any change_infos'''
      'no_related_changes',
      api.properties(
          all_gerrit_changes=[
              {
                  'host': 'chromium-review.googlesource.com',
                  'change': 1234,
                  'patchset': 1,
                  'project': 'myproject'
              },
              {
                  'host': 'chromium-review.googlesource.com',
                  'change': 456,
                  'patchset': 1,
                  'project': 'myproject'
              },
              {
                  'host': 'chromium-review.googlesource.com',
                  'change': 789,
                  'patchset': 1,
                  'project': 'myproject'
              },
          ], filtered_changes=[
              {
                  'host': 'chromium-review.googlesource.com',
                  'change': 1234,
                  'patchset': 1,
                  'project': 'myproject'
              },
              {
                  'host': 'chromium-review.googlesource.com',
                  'change': 789,
                  'patchset': 1,
                  'project': 'myproject'
              },
              {
                  'host': 'chromium-review.googlesource.com',
                  'change': 456,
                  'patchset': 1,
                  'project': 'myproject'
              },
          ]),
      api.gerrit.set_gerrit_related_changes(
          {'related': []}, step_name='Filtering Related Chain CLs'),
      api.post_process(DropExpectation))
  yield api.test(
      '''Test for all related changes. It should filter all change_infos'''
      'all_related_changes',
      api.properties(
          all_gerrit_changes=[
              {
                  'host': 'chromium-review.googlesource.com',
                  'change': 1234,
                  'patchset': 1,
                  'project': 'myproject'
              },
              {
                  'host': 'chromium-review.googlesource.com',
                  'change': 456,
                  'patchset': 1,
                  'project': 'myproject'
              },
              {
                  'host': 'chromium-review.googlesource.com',
                  'change': 789,
                  'patchset': 1,
                  'project': 'myproject'
              },
          ], filtered_changes=[]),
      api.gerrit.set_gerrit_related_changes(
          {
              'related': [
                  {
                      '_change_number': 1234,
                      '_revision_number': 1,
                      'host': 'chromium-review.googlesource.com',
                      'project': 'myproject'
                  },
                  {
                      '_change_number': 456,
                      '_revision_number': 1,
                      'host': 'chromium-review.googlesource.com',
                      'project': 'myproject'
                  },
                  {
                      '_change_number': 789,
                      '_revision_number': 1,
                      'host': 'chromium-review.googlesource.com',
                      'project': 'myproject'
                  },
              ]
          }, step_name='Filtering Related Chain CLs'),
      # Lets make sure that the function does not call gerrit_related_changes again
      api.post_process(
          DoesNotRun,
          'Filtering Related Chain CLs.call gerrit_related_changes (2)'),
      api.post_process(DropExpectation))
