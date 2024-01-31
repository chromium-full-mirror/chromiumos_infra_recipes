# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for performing various manipulations on ChromeOS manifests."""

from PB.recipes.chromeos.manifest_doctor import ManifestDoctorProperties

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'bot_cost',
    'cros_infra_config',
    'cros_source',
    'gobin',
    'repo',
    'workspace_util',
]


PROPERTIES = ManifestDoctorProperties


def RunSteps(api: RecipeApi, properties: ManifestDoctorProperties):
  with api.step.nest('validate properties'):
    if bool(properties.internal_buildspecs_bucket) != bool(
        properties.external_buildspecs_bucket):
      raise StepFailure(
          'internal_buildspecs_bucket and external_buildspecs_bucket '
          'props must be used together')

  if len(properties.buildspec_watch_paths) > 0:
    with api.step.nest('create external buildspecs'):
      cmd = ['public-buildspec']
      cmd += ['--paths', ','.join(properties.buildspec_watch_paths)]
      if properties.push:
        cmd += ['--push']
      if properties.internal_buildspecs_bucket:
        cmd += ['--internal-bucket', properties.internal_buildspecs_bucket]
      if properties.external_buildspecs_bucket:
        cmd += ['--external-bucket', properties.external_buildspecs_bucket]

      api.gobin.call('manifest_doctor', cmd)

  if len(properties.buildspec_watch_paths_legacy) > 0:
    with api.step.nest('create external buildspecs (legacy)'):
      cmd = ['public-buildspec']
      cmd += ['--paths', ','.join(properties.buildspec_watch_paths_legacy)]
      cmd += ['--legacy']
      if properties.push:
        cmd += ['--push']
      if properties.internal_buildspecs_bucket:
        cmd += ['--internal-bucket', properties.internal_buildspecs_bucket]
      if properties.external_buildspecs_bucket:
        cmd += ['--external-bucket', properties.external_buildspecs_bucket]

      api.gobin.call('manifest_doctor', cmd)

  if len(properties.project_buildspec_watch_paths
        ) > 0 and properties.project_buildspec_min_milestone > 0:
    with api.step.nest('create partner buildspecs'):
      cmd = ['project-buildspec']
      cmd += ['--paths', ','.join(properties.project_buildspec_watch_paths)]
      cmd += ['--min_milestone', properties.project_buildspec_min_milestone]
      cmd += ['--projects', ','.join(properties.project_buildspecs)]
      if properties.project_buildspec_watch_paths_other_repos:
        cmd += [
            '--other-repos',
            ','.join(properties.project_buildspec_watch_paths_other_repos)
        ]
      if properties.push:
        cmd += ['--push']

      api.gobin.call('manifest_doctor', cmd)

  if properties.local_manifest_branching_min_milestone:
    with api.bot_cost.build_cost_context(), api.workspace_util.setup_workspace(
    ):
      api.cros_source.ensure_synced_cache()
      api.cros_source.checkout_tip_of_tree()

      with api.step.nest('branch local manifests'):
        with api.context(cwd=api.workspace_util.workspace_path):
          all_projects = api.repo.project_infos()
          project_paths = []
          for project in all_projects:
            if project.name.startswith(
                'chromeos/project/') or project.name.startswith(
                    'chromeos/program/') or project.name.startswith(
                        'chromeos/overlays/chipset-'):
              project_paths.append(project.path)

          nproc = api.step(
              'nproc', ['nproc'], stdout=api.raw_io.output_text(),
              step_test_data=lambda: api.raw_io.test_api.stream_output_text(
                  '8\n')).stdout.strip()

          cmd = ['branch-local-manifest']
          cmd += ['--chromeos_checkout', api.workspace_util.workspace_path]
          cmd += [
              '--min_milestone',
              properties.local_manifest_branching_min_milestone
          ]
          cmd += ['--projects', ','.join(project_paths)]
          if api.buildbucket.build.id:
            cmd += ['--bbid', str(api.buildbucket.build.id)]
          cmd += ['-j', nproc]

          if properties.push:
            cmd += ['--push']
          api.gobin.call('manifest_doctor', cmd)


def GenTests(api: RecipeTestApi):
  _test_build_id = 8812345

  yield api.test(
      'validate',
      api.properties(
          **{'internal_buildspecs_bucket': 'chromeos-manifest-versions'}),
      api.post_check(post_process.StepFailure, 'validate properties'),
      status='FAILURE',
  )

  yield api.test(
      'basic',
      api.properties(
          **{
              'local_manifest_branching_min_milestone': 90,
              'buildspec_watch_paths': ['release/', 'test/'],
              'buildspec_watch_paths_legacy': ['buildspecs/'],
              'project_buildspec_watch_paths':
                  ['full/buildspecs/', 'buildspecs/'],
              'project_buildspec_min_milestone': 90,
              'project_buildspecs': ['galaxy/', 'foo/bar'],
              'project_buildspec_watch_paths_other_repos': ['chromeos/foo'],
              '$recipe_engine/buildbucket': {
                  'build': {
                      'id': _test_build_id
                  }
              }
          }),
      api.repo.project_infos_step_data(
          'branch local manifests', data=[
              {
                  'project': 'chromeos/program/galaxy',
                  'path': 'src/program/galaxy',
              },
              {
                  'project': 'chromeos/project/galaxy/milkyway',
                  'path': 'src/project/galaxy/milkyway',
              },
              {
                  'project': 'chromeos/foo',
                  'path': 'src/foo',
              },
          ]),
      api.post_check(post_process.StepCommandContains,
                     'create external buildspecs.run manifest_doctor',
                     ['--paths', 'release/,test/']),
      api.post_check(post_process.StepCommandContains,
                     'create external buildspecs (legacy).run manifest_doctor',
                     ['--paths', 'buildspecs/']),
      api.post_check(post_process.StepCommandContains,
                     'create partner buildspecs.run manifest_doctor', [
                         '--paths',
                         'full/buildspecs/,buildspecs/',
                         '--min_milestone',
                         '90',
                         '--projects',
                         'galaxy/,foo/bar',
                         '--other-repos',
                         'chromeos/foo',
                     ]),
      api.post_check(
          post_process.StepCommandContains,
          'branch local manifests.run manifest_doctor',
          ['--projects', 'src/program/galaxy,src/project/galaxy/milkyway']),
      api.post_check(post_process.StepCommandContains,
                     'branch local manifests.run manifest_doctor',
                     ['--min_milestone', '90']),
      api.post_check(post_process.StepCommandContains,
                     'branch local manifests.run manifest_doctor', ['-j', '8']),
      api.post_check(post_process.StepCommandContains,
                     'branch local manifests.run manifest_doctor',
                     ['--bbid', str(_test_build_id)]),
  )

  yield api.test(
      'push',
      api.properties(
          **{
              'push': True,
              'local_manifest_branching_min_milestone': 90,
              'buildspec_watch_paths': ['release/', 'test/'],
              'buildspec_watch_paths_legacy': ['buildspecs/'],
              'project_buildspec_watch_paths':
                  ['full/buildspecs/', 'buildspecs/'],
              'project_buildspec_min_milestone': 90,
              'project_buildspecs': ['galaxy/', 'foo/bar'],
              'internal_buildspecs_bucket': 'chromeos-manifest-versions',
              'external_buildspecs_bucket': 'chromiumos-manifest-versions',
          }),
      api.repo.project_infos_step_data(
          'branch local manifests', data=[
              {
                  'project': 'chromeos/program/galaxy',
                  'path': 'src/program/galaxy',
              },
              {
                  'project': 'chromeos/project/galaxy/milkyway',
                  'path': 'src/project/galaxy/milkyway',
              },
              {
                  'project': 'chromeos/foo',
                  'path': 'src/foo',
              },
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'create external buildspecs.run manifest_doctor', [
              '--push', '--internal-bucket', 'chromeos-manifest-versions',
              '--external-bucket', 'chromiumos-manifest-versions'
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'create external buildspecs (legacy).run manifest_doctor', [
              '--push', '--internal-bucket', 'chromeos-manifest-versions',
              '--external-bucket', 'chromiumos-manifest-versions'
          ]),
      api.post_check(post_process.StepCommandContains,
                     'create partner buildspecs.run manifest_doctor',
                     ['--push']),
      api.post_check(
          post_process.StepCommandContains,
          'branch local manifests.run manifest_doctor',
          ['--projects', 'src/program/galaxy,src/project/galaxy/milkyway']),
      api.post_check(post_process.StepCommandContains,
                     'branch local manifests.run manifest_doctor', ['--push']),
  )
