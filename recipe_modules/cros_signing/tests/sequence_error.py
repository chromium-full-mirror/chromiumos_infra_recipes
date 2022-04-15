# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Verify that wait_for_signing is required before retrieving signed build
metadata."""

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'cros_signing',
]

from recipe_engine import post_process


def RunSteps(api):
  with api.assertions.assertRaises(api.step.StepFailure):
    api.cros_signing.get_signed_build_metadata(None)


def GenTests(api):
  yield api.test('fails-when-get_signed_build_metadata-is-called-first',
                 api.post_check(post_process.DoesNotRun, 'parse metadata'))
