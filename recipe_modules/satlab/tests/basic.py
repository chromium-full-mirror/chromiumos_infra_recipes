# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.post_process import DoesNotRun, DropExpectation, MustRun

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'satlab',
]



def RunSteps(api):
  api.satlab.stage_build("brya-release/R100-123.123.123", "my-bucket")


def GenTests(api):
  yield api.test(
      'success', api.step_data('stage build request', retcode=0),
      api.post_process(MustRun, 'get access token for default account'),
      api.post_process(MustRun, 'write headers'),
      api.post_process(MustRun, 'stage build request'),
      api.post_process(DropExpectation))

  yield api.test(
      'fail to get token',
      api.step_data('get access token for default account', retcode=1),
      api.post_process(MustRun, 'get access token for default account'),
      api.post_process(DoesNotRun, 'write headers'),
      api.post_process(DoesNotRun, 'stage build request'),
      api.post_process(DropExpectation), status='INFRA_FAILURE')

  yield api.test(
      'fail to write header file', api.step_data('write headers', retcode=1),
      api.post_process(MustRun, 'get access token for default account'),
      api.post_process(MustRun, 'write headers'),
      api.post_process(DoesNotRun, 'stage build request'),
      api.post_process(DropExpectation), status='INFRA_FAILURE')

  yield api.test(
      'fail to stage build', api.step_data('stage build request', retcode=22),
      api.post_process(MustRun, 'get access token for default account'),
      api.post_process(MustRun, 'write headers'),
      api.post_process(MustRun, 'stage build request'),
      api.post_process(DropExpectation), status='FAILURE')
