# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import json_format

from PB.chromite.api import depgraph
from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PackageInfo
from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_history',
    'cros_relevance',
]



def RunSteps(api):
  bt = BuildTarget(name='my_build_target')
  sysroot = Sysroot(path='/build/target', build_target=bt)
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
  if api.properties.get('dep_graph'):
    dep_graph = json_format.Parse(
        api.properties.get('dep_graph'), dep_graph, ignore_unknown_fields=True)
  relevance = api.cros_relevance.postsubmit_relevance_check(
      bbcommon_pb2.GitilesCommit(id='my hash'), dep_graph)
  expected_relevance = api.properties.get('expected_relevance', True)
  api.assertions.assertEqual(relevance, expected_relevance)


def GenTests(api):

  yield api.test(
      'basic',
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_uprev_response()],
          step_name='postsubmit relevance check.buildbucket.search',
      ),
      api.post_check(post_process.MustRun, 'postsubmit relevance check'),
  )

  yield api.test(
      'annealing-not-found',
      api.post_check(post_process.MustRun, 'postsubmit relevance check'),
  )

  yield api.test(
      'force-postsubmit-relevant',
      api.properties(
          **{'$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          }}),
      api.post_check(post_process.DoesNotRun, 'postsubmit relevance check'),
  )

  bt = BuildTarget(name='my_build_target')
  sysroot = Sysroot(path='/build/target', build_target=bt)
  not_relevant_dep_graph = depgraph.DepGraph(
      sysroot=sysroot, build_target=bt, package_deps=[
          depgraph.PackageDepInfo(dependency_packages=[
              PackageInfo(
                  package_name='irrelevant',
                  category='something',
                  version='some-version',
              )
          ]),
      ])
  not_relevant_dep_graph_json = json_format.MessageToJson(
      not_relevant_dep_graph)
  yield api.test(
      'not-relevant',
      api.buildbucket.simulated_search_results(
          [api.cros_history.build_with_uprev_response()],
          step_name='postsubmit relevance check.buildbucket.search',
      ),
      api.properties(expected_relevance=False,
                     dep_graph=not_relevant_dep_graph_json),
      api.post_check(post_process.MustRun, 'postsubmit relevance check'),
  )
