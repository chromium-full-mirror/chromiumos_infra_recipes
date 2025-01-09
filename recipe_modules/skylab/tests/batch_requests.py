# -*- coding: utf-8 -*-
# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring

"""Tests for skylab.batch_requests."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'skylab',
]


def RunSteps(api):
  requests_dict = {}
  requests_dict["dedede-drallion--R132"] = {"test plan 1"}
  batch_size = 3
  batched_requests = api.skylab.batch_requests(requests_dict, batch_size)
  api.assertions.assertEqual(len(batched_requests), 1)

  requests_dict["dedede-drallion360--R132"] = {"test plan 2"}
  requests_dict["dedede-gothrax--R133"] = {"test plan 3"}
  requests_dict["dedede-drallion36--R132"] = {"test plan 4"}
  batched_requests = api.skylab.batch_requests(requests_dict, batch_size)
  total_reqs = 0
  for batch_req in batched_requests:
    total_reqs += len(batch_req)
  api.assertions.assertEqual(len(batched_requests), 2)
  api.assertions.assertEqual(total_reqs, 4)


def GenTests(api):

  yield api.test(
      'batch_request',
      api.post_process(post_process.DropExpectation),
  )
