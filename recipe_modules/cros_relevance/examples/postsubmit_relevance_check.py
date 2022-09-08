# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_history',
    'cros_relevance',
]

from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2

from PB.chromite.api import depgraph
from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageInfo

from recipe_engine import post_process

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  config = BuilderConfig()
  config.id.type = BuilderConfig.Id.POSTSUBMIT
  bt = BuildTarget(name='my_build_target')
  sysroot = Sysroot(path='/build/target', build_target=bt)
  dep_graph = depgraph.DepGraph(
      sysroot=sysroot, build_target=bt, package_deps=[
          depgraph.PackageDepInfo(dependency_packages=[
              PackageInfo(
                  package_name='irrelevant',
                  category='something',
                  version='some-version',
              )
          ]),
      ])
  relevance = api.cros_relevance.postsubmit_relevance_check(
      bbcommon_pb2.GitilesCommit(id='my hash'), dep_graph)
  api.assertions.assertFalse(relevance)
  dep_graph = depgraph.DepGraph(
      sysroot=sysroot, build_target=bt, package_deps=[
          depgraph.PackageDepInfo(dependency_packages=[
              PackageInfo(
                  package_name='ap-aogh',
                  category='chromeos-base',
                  version='0.0.1-r12845',
              )
          ]),
      ])
  relevance = api.cros_relevance.postsubmit_relevance_check(
      bbcommon_pb2.GitilesCommit(id='my hash'), dep_graph)
  api.assertions.assertTrue(relevance)


def GenTests(api):

  yield api.test(
      'annealing-not-found',
      api.post_check(post_process.StepFailure, 'postsubmit relevance check'))

  yield api.test(
      'postsubmit-check',
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_uprev_response()],
          step_name='postsubmit relevance check.buildbucket.search',
      ),
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_uprev_response()],
          step_name='postsubmit relevance check (2).buildbucket.search',
      ))
