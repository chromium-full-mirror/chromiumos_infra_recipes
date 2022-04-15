# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that instructions files are in the appropriate format."""

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'cros_signing',
]

from recipe_engine import post_process


def RunSteps(api):
  with api.assertions.assertRaises(api.step.StepFailure):
    api.cros_signing.wait_for_signing(['gs://foo.bar'])


def GenTests(api):
  yield api.test('fails-when-instructions-file-location-is-malformed',
                 api.post_check(post_process.DoesNotRun, 'parse metadata'))
