# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import json_format

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1.common import GerritChange, GitilesCommit
from PB.go.chromium.org.luci.resultdb.proto.v1.invocation import Sources, SourceSpec
from PB.recipe_modules.chromeos.metadata_json.examples.test import TestProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_infra_config',
    'metadata_json',
    'src_state',
    'test_util',
]

PROPERTIES = TestProperties

PYTHON_VERSION_COMPATIBILITY = 'PY3'

external_git_repo = 'https://chromium.googlesource.com/chromiumos/manifest'
internal_git_repo = 'https://chrome-internal.googlesource.com/chromeos/manifest-internal'
git_ref = 'snapshot'
revision = 'c' * 40


def RunSteps(api, properties):
  api.metadata_json.add_source_spec(api.cros_infra_config.config)
  metadata = api.metadata_json.get_metadata()
  source_spec = json_format.ParseDict(
      metadata.get('source_spec', {}), SourceSpec())
  api.assertions.assertEqual(source_spec, properties.expected_source_spec)


def GenTests(api):

  def test_build(build_target, number_of_gerrit_changes):
    gerrit_changes = [
        common_pb2.GerritChange(host='chromium-review.googlesource.com',
                                project='chromiumos/infra', change=12340 + i,
                                patchset=1)
        for i in range(number_of_gerrit_changes)
    ]

    return api.test_util.test_child_build(build_target, cq=True,
                                          gerrit_changes=gerrit_changes,
                                          git_repo=internal_git_repo,
                                          git_ref=git_ref,
                                          revision=revision).build

  yield api.test(
      'not-staging',
      api.test_util.test_child_build('atlas', cq=True).build,
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'public-target',
      api.test_util.test_child_build('staging-amd64-generic', cq=True,
                                     git_repo=external_git_repo,
                                     revision=revision, git_ref=git_ref).build,
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'staging-release',
      api.test_util.test_child_build(
          'staging-eve', builder_name='staging-eve-release-main').build,
      api.post_process(post_process.DropExpectation),
  )

  gitiles_commit = GitilesCommit(project='chromeos/manifest-internal',
                                 host='chrome-internal.googlesource.com',
                                 commit_hash=revision, ref=git_ref,
                                 position=999)
  gerrit_changes = [
      GerritChange(host='chromium-review.googlesource.com',
                   project='chromiumos/infra', change=12340 + i, patchset=1)
      for i in range(10)
  ]
  sources = Sources(gitiles_commit=gitiles_commit, changelists=gerrit_changes)
  expected_source_spec = SourceSpec(sources=sources)
  yield api.test(
      'basic',
      test_build('staging-atlas', number_of_gerrit_changes=10),
      api.properties(TestProperties(expected_source_spec=expected_source_spec)),
      api.post_process(post_process.DropExpectation),
  )

  expected_source_spec.sources.is_dirty = True
  yield api.test(
      'more-than-ten-changes',
      test_build('staging-atlas', number_of_gerrit_changes=11),
      api.properties(TestProperties(expected_source_spec=expected_source_spec)),
      api.post_process(post_process.DropExpectation),
  )
