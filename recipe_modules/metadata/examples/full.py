# -*- coding: utf-8 -*-

# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'metadata',
]


def RunSteps(api):
  api.assertions.assertEqual(
      api.metadata.gspath(
          api.metadata.METADATA_PAYLOADS['container'],
      ),
      'metadata/containers.jsonpb',
  )


def GenTests(api):
  yield api.test('basic')
