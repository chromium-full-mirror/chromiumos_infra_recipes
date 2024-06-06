# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process
from PB.go.chromium.org.luci.buildbucket.proto import common as bb_common_pb2

DEPS = [
    'recipe_engine/assertions',
    'failures_util',
]


def RunSteps(api):
  api.failures_util.present_run('test suite', {'bvt-tast-cq': 'www.google.com'},
                                bb_common_pb2.SUCCESS, critical=True)
  api.failures_util.present_run('test suite', {'bvt-tast-cq': 'www.google.com'},
                                bb_common_pb2.INFRA_FAILURE, critical=True)
  api.failures_util.present_run('test suite', {'bvt-tast-cq': 'www.google.com'},
                                bb_common_pb2.FAILURE, critical=True)
  api.failures_util.present_run('test suite', {'bvt-tast-cq': 'www.google.com'},
                                bb_common_pb2.FAILURE, critical=False)


def GenTests(api):
  yield api.test('basic', api.post_process(post_process.DropExpectation))
