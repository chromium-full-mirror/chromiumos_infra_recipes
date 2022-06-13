# -*- coding: utf-8 -*-

# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf.json_format import MessageToDict

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_source.cros_source import CrosSourceProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation

CHROMIUM_SRC_PROJECT = 'chromium/src'
CHROMIUM_SRC_URL = 'https://chromium.googlesource.com/{}'.format(
    CHROMIUM_SRC_PROJECT)
LKGM_PATH = 'chromeos/CHROMEOS_LKGM'
LKGM_CL_REVIEWERS = ['chrome-os-gardeners-reviews@google.com']


class CrosLkgmApi(recipe_api.RecipeApi):
  """A module to handle the LGKM process and other interactions between the
    Release & Public builders."""

  def __init__(self, properties, *args, **kwargs):
    self._full_run = properties.full_run
    self._builder_threshold_percentage = properties.builder_threshold_percentage
    self._presubmit_trybots = properties.presubmit_trybots
    self._public_build = None
    self._public_build_results = None
    super(CrosLkgmApi, self).__init__(*args, **kwargs)

  def schedule_public_build(self):
    """Schedules a public build.

    Returns: (common_pb2.Build) The scheduled build.
    """
    with self.m.step.nest('schedule public build'):
      config = self.m.cros_infra_config.config
      if not config:
        raise StepFailure(
            'could not find builder config, needed to determine branch')
      branch = config.orchestrator.gitiles_commit.ref[len('refs/heads/'):]

      is_staging = self.m.cros_infra_config.is_staging
      staging_prefix = 'staging-' if is_staging else ''
      public_orch_name = '{}public-{}-orchestrator'.format(
          staging_prefix, branch)

      buildspec_location = self.m.cros_release.buildspec.manifest_gs_path
      # We want to pass the public buildspec to the public builder.
      buildspec_location = buildspec_location.replace(
          'chromeos-manifest-versions', 'chromiumos-manifest-versions')

      request = self.m.buildbucket.schedule_request(
          bucket='staging' if is_staging else 'release',
          builder=public_orch_name,
          properties={
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_gs_path=buildspec_location))),
          },
          can_outlive_parent=True,
          tags=self.m.buildbucket.tags(
              parent_buildbucket_id=str(self.m.buildbucket.build.id)),
      )
      builds = self.m.buildbucket.schedule([request],
                                           step_name='running public builder')
      self._public_build = builds[0]
      return self._public_build

  def collect_public_build(self):
    """Collects results from the public build.

    Returns: (common_pb2.Build) The scheduled build.
    """
    with self.m.step.nest('collect public orchestrator'):
      if not self._public_build:
        raise StepFailure(
            "collect_public_build called but no public build exists")

      self._public_build_results = self.m.buildbucket.collect_build(
          self._public_build.id, step_name='collect')

  def _success_percent(self, builds):
    successful_builds = sum([b.status == common_pb2.SUCCESS for b in builds])
    return successful_builds / float(len(builds)) * 100. if len(builds) else 0

  def do_lkgm(self, release_build_results):
    """Performs the LGKM process if the build is an LKGM candidate.

    This should only be called from a release orchestrator.

    Args:
      release_build_results (list(common_pb2.Build)): list of release build
        results as returned by api.orch_menu.plan_and_run_children.
    """
    with self.m.step.nest('assess LKGM readiness') as presentation:
      if not self._is_lkgm_candidate(release_build_results):
        presentation.step_text = 'not an LKGM candidate'
        return
      else:
        presentation.step_text = 'LKGM candidate'

    self._update_lkgm()

  def _is_lkgm_candidate(self, release_build_results):
    """Determines if the build is an LKGM candidate based on child build results.

    Args:
      release_build_results (list(common_pb2.Build)): list of release builds.

    Returns: (bool) LKGM candidate status.
    """
    with self.m.step.nest('assess release build results') as presentation:
      if not release_build_results:
        presentation.step_text = 'no release builds'
        return False
      success_percent = self._success_percent(release_build_results)
      presentation.step_text = 'release builds have {:.2f}% percent success rate, threshold is {:d}%'.format(
          success_percent, self._builder_threshold_percentage)
      if success_percent <= self._builder_threshold_percentage:
        return False

    with self.m.step.nest('assess public build results') as presentation:
      output_props = self._public_build_results.output.properties
      child_build_ids = output_props[
          'child_builds'] if 'child_builds' in output_props else []
      child_builds = self.m.buildbucket.get_multi(
          [int(bbid) for bbid in child_build_ids],
          step_name='get public builders').values() if child_build_ids else []

      if self._public_build_results.status != common_pb2.SUCCESS and not child_builds:
        # If the public orchestrator failed AND there are no child builds, we don't want
        # to consider this version for LKGM.
        presentation.step_text = 'public orchestrator failed and did not report any child builds'
        return False
      else:
        success_percent = self._success_percent(child_builds)
        presentation.step_text = 'public builds have {:.2f}% percent success rate, threshold is {:d}%'.format(
            success_percent, self._builder_threshold_percentage)
        if success_percent <= self._builder_threshold_percentage:
          return False
    return True

  def _update_lkgm(self):
    """Creates, uploads, and submits an LKGM CL."""
    with self.m.step.nest('create LKGM CL'):
      chromium_src_dir = self.m.path.mkdtemp()
      self.m.git.clone(CHROMIUM_SRC_URL, single_branch=True, depth=1,
                       target_path=chromium_src_dir)

      with self.m.context(cwd=chromium_src_dir):
        platform_version = self.m.cros_version.version.platform_version
        self.m.file.write_text('update LKGM file', LKGM_PATH, platform_version)
        commit_lines = [
            'Automated Commit: LKGM {} for chromeos.'.format(platform_version),
            '',
            'Uploaded by {}'.format(self.m.buildbucket.build_url()),
            '',
        ] + [
            'CQ_INCLUDE_TRYBOTS=luci.chrome.try:{}'.format(trybot)
            for trybot in self._presubmit_trybots
        ] + [
            '',
            'Cr-Automation-Id: cros_lkgm',
        ]
        commit_message = '\n'.join(commit_lines)

        with self.m.step.nest('commit in {}'.format(CHROMIUM_SRC_PROJECT)):
          self.m.git.add([LKGM_PATH])
          self.m.git.commit(commit_message)

        with self.m.step.nest('create CL'):
          change = self.m.gerrit.create_change(
              CHROMIUM_SRC_PROJECT,
              reviewers=LKGM_CL_REVIEWERS,
              hashtags=['chrome-lkgm'],
              project_path=chromium_src_dir,
          )
          # Then set labels.
          labels = {
              True: {
                  self.m.gerrit.Label.BOT_COMMIT: 1,
                  self.m.gerrit.Label.COMMIT_QUEUE: 2,
              },
              False: {
                  self.m.gerrit.Label.BOT_COMMIT: 1,
                  self.m.gerrit.Label.COMMIT_QUEUE: 1,
              },
          }.get(self._full_run)
          self.m.gerrit.set_change_labels(change, labels)
