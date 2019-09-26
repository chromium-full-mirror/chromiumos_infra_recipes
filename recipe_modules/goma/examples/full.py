# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'goma',
]

def RunSteps(api):
  api.assertions.assertEqual(str(api.goma.goma_dir), '[START_DIR]/cipd/goma')

  # Expectations should show it didn't fetch again.
  api.assertions.assertEqual(str(api.goma.goma_dir), '[START_DIR]/cipd/goma')

  api.assertions.assertEqual(
      str(api.goma.goma_client_json),
      '/creds/service_accounts/service-account-goma-client.json');

def GenTests(api):
  yield api.test('basic')
