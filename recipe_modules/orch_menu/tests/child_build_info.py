# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'orch_menu',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):

  api.orch_menu.add_child_info_to_output_property()


def GenTests(api):

  def _child_builds(child_builder_names):
    return [
        build_pb2.Build(id=101 + i, builder={
            'builder': builder,
            'bucket': 'cq'
        }) for i, builder in enumerate(child_builder_names)
    ]

  yield api.test(
      'basic',
      api.buildbucket.try_build(project='chromeos', bucket='cq',
                                builder='cq-orchestrator'),
      api.buildbucket.simulated_search_results(
          _child_builds(['atlas-cq', 'dedede-cq'])),
      api.post_check(post_process.PropertyEquals, 'child_builds',
                     ['101', '102']),
  )
