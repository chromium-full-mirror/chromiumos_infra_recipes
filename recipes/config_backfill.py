# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Copy legacy configuration and generate backfilled configuration."""

# When run, this recipe will copy configured legacy configuration data to
# per-project repos (including model.yaml and HWID data).  After the data
# is copied, the config.jsonproto is generated from any existing starlark,
# and the join_config_payloads.py script is used to backfill the legacy
# configuration information into a joined.jsonproto.
#
# Any resulting changes are then committed to the configured destination.

import collections
import textwrap
import urlparse

from PB.recipes.chromeos.config_backfill import ConfigBackfillProperties
from recipe_engine import post_process

# import protos
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2

# Recipe dependencies
DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/futures',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_source',
    'easy',
    'gerrit',
    'git',
    'git_txn',
    'gitiles',
    'repo',
    'src_state',
]

PROPERTIES = ConfigBackfillProperties

CROS_EXTERNAL = 'https://chromium.googlesource.com/chromiumos'
CROS_INTERNAL = 'https://chrome-internal.googlesource.com/chromeos'

# Paths to repos
PATH_CROS_CONFIG = "src/config"
PATH_CROS_HWID = "src/platform/chromeos-hwid"
PATH_CROS_OVERLAYS = "src/overlays"
PATH_CROS_OVERLAYS_PRIVATE = "src/private-overlays"

# Repo URL configuration
PUBLIC_BASEBOARD_REPO = CROS_EXTERNAL + '/overlays/board-overlays'
PRIVATE_BASEBOARD_REPO = CROS_INTERNAL + '/overlays/baseboard-{program}-private'

# Paths to scripts
JOIN_SCRIPT_PATH = 'payload_utils/join_config_payloads.py'

# path to cloud credentials
CLOUD_CREDS_PATH = '/creds/service_accounts/service-account-chromeos.json'


def require(cond, message):
  """Require a given condition be true or throw a ValueError."""
  if not cond:  # pragma: nocover
    raise ValueError(message)


def split_overlay_project(api, repo):
  """Take a private overlay URL and parse out project name."""
  parts = urlparse.urlparse(repo)
  require(
      parts.netloc == api.src_state.internal_manifest.host,
      "overlay isn't in internal repo",
  )
  return parts.path


def create_portage_workaround(api):
  """Hack around needing a full portage environment for reef/fizz.

  Reef/fizz require their baseboard overlay to include common files.  We can
  work around this by using symlinks to simulate the overlay.
  """

  path_cros_repo = api.context.cwd

  # TODO(crbug.com/1144956).  This is a workaround for fizz and reef.  They're
  # unique in that they expect their baseboard overlay to be available so they
  # can include a common yaml file from it.  We don't have portage available
  # so we have to clone the repos and hack it with symlinks.  Once the mentioned
  # bug is resolved, we can make this more consistent for all projects.
  def _copy_baseboard(step_text, src_path, dst_path):
    """Copy files from baseboard overlay to project overlay.

    Args:
        step_text (str): display text for the step
        src_path (str): path in the baseboard overlay to copy from
        dst_path (str): path in overlay to copy files to
    """

    with api.step.nest(step_text):
      api.path.mock_add_paths(src_path)
      if api.path.exists(src_path):
        api.file.copytree(
            'copying files',
            src_path,
            dst_path,
        )

  ### main function body
  # These paths aren't consistent so we'll just enumerate them
  config_paths = {
      'reef': {
          'public_baseboard':
              'chromeos-base/chromeos-config-bsp-baseboard/files',
          'public_overlay':
              'chromeos-base/chromeos-config-bsp/files/include-public',
          'private_baseboard':
              'chromeos-base/chromeos-config-bsp-baseboard-private/files',
          'private_overlay':
              'chromeos-base/chromeos-config-bsp-private/files/include-private',
      },
      'fizz': {
          'public_baseboard':
              'chromeos-base/chromeos-config-bsp-baseboard/files',
          'public_overlay':
              'chromeos-base/chromeos-config-bsp-fizz/files/include-public',
          'private_baseboard':
              'chromeos-base/chromeos-config-bsp-baseboard/files/include',
          'private_overlay':
              'chromeos-base/chromeos-config-bsp-fizz-private/files/include',
      }
  }

  for program in ['reef', 'fizz']:
    _copy_baseboard(
        step_text='[%s] configuring public baseboard overlay' % program,
        src_path=path_cros_repo.join(
            'src/overlays/baseboard-{}'.format(program),
            config_paths[program]['public_baseboard'],
        ),
        dst_path=path_cros_repo.join(
            "src/overlays/overlay-{}".format(program),
            config_paths[program]['public_overlay'],
        ),
    )

    _copy_baseboard(
        step_text='[%s] configuring private baseboard overlay' % program,
        src_path=path_cros_repo.join(
            "src/private-overlays/baseboard-{}-private".format(program),
            config_paths[program]['private_baseboard'],
        ),
        dst_path=path_cros_repo.join(
            "src/private-overlays/overlay-{}-private".format(program),
            config_paths[program]['private_overlay'],
        ),
    )


def config_merger(api, config, path_cros_repo, step_pres):
  """Create a closure to merge configs.

  Meant to be called from git_txn.update_ref, which requires a single
  function taking no arguments, so close on what we need.

  Args:
    api: Reference to recipes API
    config: Merge config to execute
    path_cros_repo: Path to root of ChromeOS checkout
    step_pres: Step presentation instance

  Return:
    closure to execute merge operation
  """

  def merge():
    """Execute merge operation on repo"""

    path_project_repo = path_cros_repo.join("src/project/{}/{}".format(
        config.program_name.lower(),
        config.project_name.lower(),
    ))

    path_imported = path_project_repo.join('imported')
    path_generated = path_project_repo.join('generated')

    path_public_yaml = None
    if config.public_yaml_path:
      path_public_yaml = path_cros_repo.join(
          PATH_CROS_OVERLAYS,
          config.public_yaml_path,
      )

    path_private_yaml = None
    if config.HasField('private_yaml'):
      path_private_yaml = path_cros_repo.join(
          PATH_CROS_OVERLAYS_PRIVATE,
          split_overlay_project(api, config.private_yaml.repo).split("/")[-1],
          config.private_yaml.path,
      )

    path_hwid = None
    if config.hwid_key:
      path_hwid = path_cros_repo.join(
          PATH_CROS_HWID,
          "v3/{}".format(config.hwid_key),
      )

    with api.context(cwd=path_project_repo):
      # Create import directory.
      api.file.ensure_directory(
          'ensure %s directory exists' % path_imported,
          path_imported,
      )

      # Copy public model.yaml to import.
      if path_public_yaml:
        dst_path = path_imported.join('public_model.yaml')
        api.file.copy(
            'copy public model.yaml',
            path_public_yaml,
            dst_path,
        )
        api.git.add([dst_path])

      # Copy private model.yaml to import.
      if path_private_yaml:
        dst_path = path_imported.join('private_model.yaml')
        api.file.copy(
            'copy private model.yaml',
            path_private_yaml,
            dst_path,
        )
        api.git.add([dst_path])

      # Copy the HWID database.
      if config.hwid_key:
        dst_path = path_imported.join("hwid")
        api.file.copy(
            'copy HWID database',
            path_hwid,
            dst_path,
        )
        api.git.add([dst_path])

      # create generate/ if it doesn't exist
      api.file.ensure_directory(
          'ensure %s directory exists' % path_generated,
          path_generated,
      )

      # Mock existence of config bundle for tests
      path_config_bundle = path_generated.join('config.jsonproto')
      api.path.mock_add_paths(path_config_bundle)

      # Merge backfilled data into a ConfigBundle payload
      cmd = [path_cros_repo.join(PATH_CROS_CONFIG, JOIN_SCRIPT_PATH)]
      cmd += ['--log', 'DEBUG']
      cmd += ['--project-name', config.project_name]
      cmd += ['--program-name', config.program_name]

      if path_public_yaml:
        cmd += ['--public-model', path_public_yaml]
      if path_private_yaml:
        cmd += ['--private-model', path_private_yaml]
      if path_hwid:
        cmd += ['--hwid', path_hwid]

      # TODO(crbug.com/1154322): remove merged configuration generation once
      # the merge functionality is available, just call gen_config instead.
      # Generate output joined with existing starlark config
      if api.path.exists(path_config_bundle):
        cmd += ['--config-bundle', path_config_bundle]

      # configure environment to point to proper credentials file for GCP access
      with api.context(env={
          'GOOGLE_APPLICATION_CREDENTIALS': CLOUD_CREDS_PATH,
      }):
        # generate the import-only config (no merging with config.jsonproto)
        path_imported_config = path_generated.join('imported.jsonproto')
        api.step("Generate imported configuration", ["vpython"] + cmd + [
            '--import-only',
            '--output',
            path_imported_config,
        ])
        api.git.add([path_imported_config])

        # generate joined config (with merging)
        path_merged_config = path_generated.join('joined.jsonproto')
        api.step("Generate joined configuration", ["vpython"] + cmd + [
            '--output',
            path_merged_config,
        ])
        api.git.add([path_merged_config])

    # Commit changes (if any)
    with api.step.nest('diffing repo to find changes'):
      changed_files = api.git.get_diff_files('HEAD')
      if changed_files:
        step_pres.logs['changed files'] = ", ".join(changed_files)
      else:
        step_pres.step_summary_text = "no files changed"
        return False

      # Add and commit
      commit_msg = textwrap.dedent(
          '''\
        Merging legacy configs.

        Cr-Build-Url: {build_url}
        Cr-Automation-Id: {automation_id}'''.format(
              build_url=api.buildbucket.build_url(),
              automation_id='config_backfill'),
      )

      api.git.commit(commit_msg)
      return True

  return merge


def backfill_project(api, properties, config):
  """Backfill an individual project.

  Expects to be run in the root of the chromeos checkout.

  Args:
    config (ConfigBackfillProperties.ProjectConfig) - configuration for project

  Return:
    (program, project, commit_hash)
    or None if no commit made
  """

  program = config.program_name.lower()
  project = config.project_name.lower()

  path_cros_repo = api.context.cwd
  path_project_repo = path_cros_repo.join("src/project/{}/{}".format(
      program, project))

  with api.step.nest("processing {}/{}".format(program,
                                               project)) as presentation:
    # Check that project is checked out
    if not api.path.exists(path_project_repo):
      presentation.step_summary_text = "project not checked out"
      return None

    # Update the repo atomically
    with api.context(cwd=path_project_repo):
      project_info = api.repo.project_info()

      updated = api.git_txn.update_ref(
          project_info.remote,
          config_merger(api, config, path_cros_repo, presentation),
          ref=project_info.branch,
          dry_run=api.cros_infra_config.is_staging,
      )

      if updated:
        commit_hash = api.git.head_commit()

        # don't actually link to commit in staging (because it doesn't exist)
        if api.cros_infra_config.is_staging:
          presentation.step_summary_text = "[%s]" % commit_hash[:8]
        else:
          url = api.git.remote_url(project_info.remote) + "/+/" + commit_hash
          presentation.step_summary_text = "[%s](%s)" % (commit_hash[:8], url)

        return (program, project, commit_hash)
      return None


def RunSteps(api, properties):
  api.cros_infra_config.configure_builder()

  configs = properties.configs

  # TODO(crbug.com/1193491): remove once migrated to the new config format
  if properties.dest_repo:
    config = configs.add()
    config.public_yaml_path = properties.public_yaml.path
    config.private_yaml.MergeFrom(properties.private_yaml)
    config.hwid_key = properties.hwid_key
    config.project_name = properties.project_name
    config.program_name = properties.program_name

  # setup overlays, sync projects and move to tip-of-tree
  with api.cros_source.checkout_overlays_context():
    api.cros_source.ensure_synced_cache()
    api.cros_source.checkout_tip_of_tree()

    # run backfill
    with api.context(cwd=api.cros_source.workspace_path):
      with api.step.nest("create portage workaround symlinks"):
        create_portage_workaround(api)

      futures = [
          api.futures.spawn(backfill_project, api, properties, config)
          for config in configs
      ]
      api.futures.wait(futures)

      # parse results
      output_commits = collections.defaultdict(dict)
      commits = []
      errors = []
      for f in futures:
        ex = f.exception()
        if ex:
          errors.append(ex)
          continue

        result = f.result()
        if result:
          commits.append(result)
          program, project, commit = result
          output_commits[program][project] = commit

      # save results in output properties
      api.easy.set_properties_step(commits=output_commits)

      # create summary markdown
      COMMIT_TEMPLATE = \
        "- {program}/{project} [{commit_short}]("                      \
          "https://chrome-internal.googlesource.com/chromeos/project/" \
          "{program}/{project}/+/{commit_sha}"                         \
        ")"

      lines = ["{} changes made".format(len(commits))]
      for commit in sorted(commits):
        program, project, commit_sha = commit
        lines.append(
            COMMIT_TEMPLATE.format(
                program=program,
                project=project,
                commit_short=commit_sha[:8],
                commit_sha=commit_sha,
            ),
        )
      lines.append("")

      if errors:
        lines.append("{} errors".format(len(errors)))
        for error in errors:
          lines.append("- {}".format(error))

      return result_pb2.RawResult(
          status=common_pb2.FAILURE if errors else common_pb2.SUCCESS,
          summary_markdown="\n".join(lines),
      )


def mock_workspace_path(api, path):
  return api.path.exists(
      api.path["start_dir"].join(
          "chromiumos_workspace",
          path,
      ),
  )


def GenTests(api):

  def StepSummaryEquals(check, step_odict, step, expected):
    """Check that the step's step_summary_text equals given value.

    Args:
      step (str) - The step to check the step_text of
      expected (str) - The expected value of the step_text

    Usage:
      yield TEST + api.post_process(
          StepSummaryEquals, 'step-name', 'expected-text'
      )
    """
    check(step_odict[step].step_summary_text == expected)

  yield api.test(
      'basic',
      api.properties(
          **{
              'dest_repo': 'https://example.com/some/project/repo',
              'public_yaml': {
                  'repo': 'https://example.com/public/',
                  'path': 'some/model.yaml'
              },
              'private_yaml': {
                  'repo': CROS_INTERNAL + '/private/',
                  'path': 'some/model.yaml'
              },
              'hwid_key': 'some_key',
              'project_name': 'test_project',
              'program_name': 'test_program',
          }),
      mock_workspace_path(api, 'src/project/test_program/test_project'),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'backfill_error',
      api.properties(
          **{
              'dest_repo': 'https://example.com/some/project/repo',
              'public_yaml': {
                  'repo': 'https://example.com/public/',
                  'path': 'some/model.yaml'
              },
              'private_yaml': {
                  'repo': CROS_INTERNAL + '/private/',
                  'path': 'some/model.yaml'
              },
              'hwid_key': 'some_key',
              'project_name': 'test_project',
              'program_name': 'test_program',
          }),
      api.step_data(
          'processing test_program/test_project'
          '.git transaction'
          '.Generate imported configuration', retcode=1),
      mock_workspace_path(api, 'src/project/test_program/test_project'),
      api.post_process(post_process.StatusFailure),
  )

  yield api.test(
      'staging_no_commit',
      api.buildbucket.generic_build(builder="staging-backfiller"),
      api.properties(
          **{
              'dest_repo': 'https://example.com/some/project/repo',
              'public_yaml': {
                  'repo': 'https://example.com/public/',
                  'path': 'some/model.yaml'
              },
              'private_yaml': {
                  'repo': CROS_INTERNAL + '/private/',
                  'path': 'some/model.yaml'
              },
              'hwid_key': 'some_key',
              'project_name': 'test_project',
              'program_name': 'test_program',
          }),
      mock_workspace_path(api, 'src/project/test_program/test_project'),
      api.post_process(
          post_process.StepCommandContains,
          "processing test_program/test_project"
          ".git transaction"
          ".git push",
          ["git", "push", "--dry-run"],
      ),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'not_checked_out',
      api.properties(
          **{
              'dest_repo': 'https://example.com/some/project/repo',
              'public_yaml': {
                  'repo': 'https://example.com/public/',
                  'path': 'some/model.yaml'
              },
              'private_yaml': {
                  'repo': CROS_INTERNAL + '/private/',
                  'path': 'some/model.yaml'
              },
              'hwid_key': 'some_key',
              'project_name': 'test_project',
              'program_name': 'test_program',
          }),
      api.post_process(
          StepSummaryEquals,
          'processing test_program/test_project',
          'project not checked out',
      ),
      api.post_process(post_process.StatusSuccess),
  )

  yield api.test(
      'no_changed_files',
      api.properties(
          **{
              'dest_repo': 'https://example.com/some/project/repo',
              'public_yaml': {
                  'repo': 'https://example.com/public/',
                  'path': 'some/model.yaml'
              },
              'private_yaml': {
                  'repo': CROS_INTERNAL + '/private/',
                  'path': 'some/model.yaml'
              },
              'hwid_key': 'some_key',
              'project_name': 'test_project',
              'program_name': 'test_program',
          }),
      mock_workspace_path(api, 'src/project/test_program/test_project'),
      api.step_data(
          'processing test_program/test_project'
          '.git transaction'
          '.diffing repo to find changes.git diff',
          stdout=api.raw_io.output('')),
  )
