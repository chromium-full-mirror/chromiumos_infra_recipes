# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'gerrit',
    'pupr',
]

import collections

from PB.recipes.chromeos.generator import (
    RetryClPolicy,
    NO_RETRY,
    RETRY_LATEST_OR_LATEST_PINNED,
    RETRY_LATEST_PINNED,
)


def RunSteps(api):
  api.assertions.assertEqual(api.pupr.identify_retry(NO_RETRY, []), None)

  changes = [{
      "info": {
          "_number": 1,
          "created": "2020-10-22 18:54:00.000000000",
          "hashtags": [],
          "messages": [{
              "message": "Patch Set 1:\n\nFailed builds: ..."
          }]
      }
  }, {
      "info": {
          "_number": 2,
          "created": "2020-10-23 18:54:00.000000000",
          "hashtags": [],
          "messages": [{
              "message": "Patch Set 1:\n\nFailed builds: ..."
          }],
      }
  }, {
      "info": {
          "_number": 3,
          "created": "2020-10-24 18:54:00.000000000",
          "hashtags": [],
          "messages": [],
      }
  }]
  open_cls = [
      api.gerrit.PatchSet(collections.defaultdict(str, change))
      for change in changes
  ]
  # Latest CL.
  api.assertions.assertEqual(
      api.pupr.identify_retry(RETRY_LATEST_OR_LATEST_PINNED,
                              open_cls).change_id, 2)
  # No pinned CLs, so no retry CL.
  api.assertions.assertEqual(
      api.pupr.identify_retry(RETRY_LATEST_PINNED, open_cls), None)

  changes = [{
      "info": {
          "_number":
              1,
          "created":
              "2020-10-22 18:54:00.000000000",
          "hashtags": [api.pupr.HASHTAG_PINNED_RETRY],
          "messages": [{
              "message": "Patch Set 1:\n\nCQ is trying the patch..."
          }, {
              "message": "Patch Set 1:\n\nFailed builds: ..."
          }, {
              "message": "Quote: Patch Set 1:\n\nCQ is trying the patch..."
          }],
      }
  }, {
      "info": {
          "_number": 2,
          "created": "2020-10-23 18:54:00.000000000",
          "hashtags": [],
          "messages": [{
              "message": "Patch Set 1:\n\nFailed builds: ..."
          }],
      }
  }]
  open_cls = [
      api.gerrit.PatchSet(collections.defaultdict(str, change))
      for change in changes
  ]
  # Pinned CL should be selected despite the presence of a more recent failed CL.
  api.assertions.assertEqual(
      api.pupr.identify_retry(RETRY_LATEST_OR_LATEST_PINNED,
                              open_cls).change_id, 1)

  changes = [{
      "info": {
          "_number":
              1,
          "created":
              "2020-10-22 18:54:00.000000000",
          "hashtags": [api.pupr.HASHTAG_PINNED_RETRY],
          "messages": [{
              "message": "Patch Set 1:\n\nCQ is trying the patch..."
          }, {
              "message": "Patch Set 1:\n\nFailed builds: ..."
          }, {
              "message": "Patch Set 2:\n\nCQ is trying the patch..."
          }],
      }
  }]
  open_cls = [
      api.gerrit.PatchSet(collections.defaultdict(str, change))
      for change in changes
  ]
  # Most recent failed CL is currently running, no retry.
  api.assertions.assertEqual(
      api.pupr.identify_retry(RETRY_LATEST_OR_LATEST_PINNED, open_cls), None)


def GenTests(api):
  yield api.test('basic')
