# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/path',
    'artifacts'
]


def RunSteps(api):
  build_report = api.properties['build_report']
  artifacts = api.properties['artifacts']
  
  api.artifacts.create_and_upload(
    'execute tests',
    build_report=build_report,
    artifacts=artifacts)


def GenTests(api):
  yield (
    api.test('basic') +
    api.properties(
      build_report=dict(
        build_target='build_target',
        version='R100-1234.5.6',
      ),
      artifacts=['hw', 'vm']
    )
  )

  yield (
    api.test('invalid_artifact') +
    api.properties(
      build_report=dict(
        build_target='build_target',
        version='R100-1234.5.6',
      ),
      artifacts=['invalid']
    )
    + api.expect_exception("ValueError")
  )
