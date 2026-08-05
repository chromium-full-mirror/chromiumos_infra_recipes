# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for ChromeOS LKGM (Last Known Good Manifest)."""

from typing import List

from google.protobuf.json_format import MessageToDict

from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.recipe_modules.chromeos.cros_source.cros_source import CrosSourceProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure



class CrosLkgmApi(recipe_api.RecipeApi):
  """A module to handle the LGKM process and other interactions between the
    Release & Public builders."""

  def __init__(self, properties, *args, **kwargs):
    self._enable_lkgm = properties.enable_lkgm
    self._enable_pupr = properties.enable_pupr
    self._pupr_builder_name = properties.pupr_builder_name
    self._full_run = properties.full_run
    self._builder_threshold_percentage = properties.builder_threshold_percentage
    self._required_green_builders = properties.required_green_builders
    self._public_build = None
    self._public_build_results = None
    self._lkgm_skipped_reason = None
    super().__init__(*args, **kwargs)

  @property
  def lkgm_skipped_reason(self) -> str | None:
    """Return why LKGM was skipped, if applicable."""
    return self._lkgm_skipped_reason

  @staticmethod
  def _format_builder_names(names: List[str]) -> str:
    """Formats a list of builder names concisely, e.g. prefix-{board1,board2}-suffix."""
    if not names:  # pragma: no cover
      return ''
    unique_names = list(dict.fromkeys(names))
    if len(unique_names) == 1:
      return unique_names[0]

    # Find longest common prefix.
    prefix = unique_names[0]
    for name in unique_names[1:]:
      while not name.startswith(prefix):
        prefix = prefix[:-1]

    # Find longest common suffix among remainders.
    suffix = unique_names[0][len(prefix):]
    for name in unique_names[1:]:
      name_remaining = name[len(prefix):]
      while not name_remaining.endswith(suffix):
        suffix = suffix[1:]

    middles = [
        name[len(prefix):len(name) - len(suffix)] for name in unique_names
    ]
    return f'{prefix}{{{",".join(middles)}}}{suffix}'

  @property
  def has_public_build(self):
    """Check if a public build was scheduled."""
    return self._public_build is not None

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
      # Allow main release branches to build from snapshot manifests.
      branch = 'main' if branch in ['snapshot', 'staging-snapshot'] else branch

      is_staging = self.m.cros_infra_config.is_staging
      staging_prefix = 'staging-' if is_staging else ''
      public_orch_name = '{}public-{}-orchestrator'.format(
          staging_prefix, branch)

      buildspec_location = self.m.cros_release.buildspec.manifest_gs_path
      # We want to pass the public buildspec to the public builder.
      buildspec_location = buildspec_location.replace(
          'chromeos-manifest-versions', 'chromiumos-manifest-versions')

      request = self.m.buildbucket.schedule_request(
          bucket='staging' if is_staging else 'chromiumos',
          builder=public_orch_name,
          properties={
              '$chromeos/cros_source':
                  MessageToDict(
                      CrosSourceProperties(
                          sync_to_manifest=ManifestLocation(
                              manifest_gs_path=buildspec_location),
                          use_external_source_cache=True)),
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
            'collect_public_build called but no public build exists')

      #TODO: Bring down the collect timeout after investigation. b/304094706
      self._public_build_results = self.m.buildbucket.collect_build(
          self._public_build.id, step_name='collect', timeout=60 * 60 * 13)

  def do_lkgm_via_pupr(self, gitiles_commit: GitilesCommit):
    """Triggers cros_lkgm.pupr if conditions are met.

    Checks if enable_lkgm and enable_pupr are True, if builder aggregated greenness
    is >= builder_threshold_percentage, and if configured required builders
    are all green with at least one being relevant.

    Args:
      gitiles_commit: GitilesCommit to trigger from.
    """
    if not self._enable_lkgm:
      self._lkgm_skipped_reason = 'LKGM is not enabled'
      return
    if not self._enable_pupr:
      self._lkgm_skipped_reason = 'PUpr is not enabled'
      return

    with self.m.step.nest('do lkgm via pupr') as presentation:
      if not self._pupr_builder_name:
        presentation.step_text = 'no PUpr builder name configured, skipping'
        self._lkgm_skipped_reason = 'no PUpr builder name configured'
        return

      # Intentionally catch all exceptions to ensure we do not break snapshot
      # and release builders at this experimental stage.
      try:
        critical_build_scores = [
            gt.build_score
            for gt in self.m.greenness.builder_greenness_dict.values()
            if gt.critical and gt.build_score != -1
        ]
        if not critical_build_scores:
          aggregated_greenness = 0
        else:
          aggregated_greenness = sum(critical_build_scores) / len(
              critical_build_scores)

        presentation.step_text = (
            'aggregated greenness: {:.2f}%, threshold: {:d}%'.format(
                aggregated_greenness, self._builder_threshold_percentage))

        if aggregated_greenness < self._builder_threshold_percentage:
          presentation.step_text += ' (below threshold, skipping PUpr)'
          self._lkgm_skipped_reason = (
              f'aggregated greenness: {aggregated_greenness:.2f}%, threshold:'
              f' {self._builder_threshold_percentage}% (below threshold)')
        elif self._required_green_builders:
          not_green_builders = [
              b for b in self._required_green_builders
              if b not in self.m.greenness.builder_greenness_dict or
              self.m.greenness.builder_greenness_dict[b].build_score != 100
          ]
          has_relevant = any(self.m.greenness.builder_greenness_dict[b].relevant
                             for b in self._required_green_builders
                             if b in self.m.greenness.builder_greenness_dict)
          if not_green_builders:
            formatted_not_green = self._format_builder_names(not_green_builders)
            presentation.step_text += (
                f' (required builders not green: {formatted_not_green}, skipping PUpr)'
            )
            self._lkgm_skipped_reason = (
                f'required builders not green: {formatted_not_green}')
          elif not has_relevant:
            formatted_required = self._format_builder_names(
                self._required_green_builders)
            presentation.step_text += (
                f' (at least one required builder in {formatted_required} needs to be relevant, skipping PUpr)'
            )
            self._lkgm_skipped_reason = (
                f'at least one required builder in {formatted_required} needs to be relevant'
            )
          else:
            self._lkgm_skipped_reason = None
            self._trigger_pupr(gitiles_commit)
        else:
          self._lkgm_skipped_reason = None
          self._trigger_pupr(gitiles_commit)
      except Exception as e:  # pylint: disable=broad-exception-caught
        presentation.status = self.m.step.FAILURE
        presentation.step_text = f'failed: {e}'
        self._lkgm_skipped_reason = f'failed: {e}'

  def _trigger_pupr(self, gitiles_commit: GitilesCommit):
    is_staging = self.m.cros_infra_config.is_staging

    project = 'chromeos'
    job = self._pupr_builder_name
    if is_staging and not job.startswith('staging-'):
      job = f'staging-{job}'

    repo = self.m.gitiles.repo_url(gitiles_commit)
    ref = gitiles_commit.ref
    revision = gitiles_commit.id

    properties = {
        'triggers': [{
            'gitiles': {
                'repo': repo,
                'ref': ref,
                'revision': revision,
            }
        }]
    }
    buildbucket_trigger = self.m.scheduler.BuildbucketTrigger(
        properties=properties,
        inherit_tags=False,
    )
    self.m.scheduler.emit_trigger(
        buildbucket_trigger,
        project=project,
        jobs=[job],
        step_name=f'trigger {job}',
    )
