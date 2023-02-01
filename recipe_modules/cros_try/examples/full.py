# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_try.cros_try import CrosTryProperties
from PB.recipe_modules.recipe_engine.buildbucket.properties import InputProperties

DEPS = [
    'recipe_engine/properties',
    'cros_try',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.cros_try.check_try_version()


def GenTests(api):
  yield api.test(
      'not-try-build',
      api.properties(**{
          '$chromeos/cros_try': CrosTryProperties(enforce_support=True),
      }),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'try-build-unsupported-unenforced',
      api.properties(
          **{
              '$recipe_engine/buildbucket':
                  InputProperties(
                      build=build_pb2.Build(tags=[
                          common_pb2.StringPair(key='tryjob-launcher',
                                                value='sundar@google.com')
                      ])),
          }),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'try-build-unsupported',
      api.properties(
          **{
              '$chromeos/cros_try':
                  CrosTryProperties(enforce_support=True),
              '$recipe_engine/buildbucket':
                  InputProperties(
                      build=build_pb2.Build(tags=[
                          common_pb2.StringPair(key='tryjob-launcher',
                                                value='sundar@google.com')
                      ])),
          }),
      api.post_check(post_process.StepFailure, 'check `cros try` version'),
      api.post_check(post_process.StatusFailure),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'try-build-supported',
      api.properties(
          **{
              '$chromeos/cros_try':
                  CrosTryProperties(enforce_support=True, supported_build=True),
              '$recipe_engine/buildbucket':
                  InputProperties(
                      build=build_pb2.Build(tags=[
                          common_pb2.StringPair(key='tryjob-launcher',
                                                value='sundar@google.com')
                      ])),
          }),
      api.post_check(post_process.StepSuccess, 'check `cros try` version'),
      api.post_check(post_process.StatusSuccess),
      api.post_process(post_process.DropExpectation),
  )
