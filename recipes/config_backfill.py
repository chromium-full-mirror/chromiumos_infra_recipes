# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
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
from urllib.parse import urlparse

from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builds_service as builds_service_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.config_backfill import ConfigBackfillProperties
from PB.testplans.generate_test_plan import BuildPayload
from recipe_engine import post_process

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
    'cros_artifacts',
    'cros_infra_config',
    'cros_source',
    'easy',
    'git',
    'git_txn',
    'repo',
    'src_state',
]


PROPERTIES = ConfigBackfillProperties

CROS_EXTERNAL = 'https://chromium.googlesource.com/chromiumos'
CROS_INTERNAL = 'https://chrome-internal.googlesource.com/chromeos'

# Paths to repos
PATH_CROS_CONFIG = 'src/config'
PATH_CROS_HWID = 'src/platform/chromeos-hwid'
PATH_CROS_OVERLAYS = 'src/overlays'
PATH_CROS_OVERLAYS_PRIVATE = 'src/private-overlays'

# Repo URL configuration
PUBLIC_BASEBOARD_REPO = CROS_EXTERNAL + '/overlays/board-overlays'
PRIVATE_BASEBOARD_REPO = CROS_INTERNAL + '/overlays/baseboard-{program}-private'

# Paths to scripts
JOIN_SCRIPT_PATH = 'payload_utils/join_config_payloads.py'

# path to cloud credentials
CLOUD_CREDS_PATH = '/creds/service_accounts/service-account-chromeos.json'

BackfillStatus = collections.namedtuple(
    'BackfillStatus',
    ['missing', 'program', 'project', 'commit'],
)


def require(cond, message):
  """Require a given condition be true or throw a ValueError."""
  if not cond:  # pragma: nocover
    raise ValueError(message)


def split_overlay_project(api, repo):
  """Take a private overlay URL and parse out project name."""
  parts = urlparse(repo)
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
              'chromeos-base/chromeos-config-bsp/files/include-public',
          'private_baseboard':
              'chromeos-base/chromeos-config-bsp-baseboard-private/files/include',
          'private_overlay':
              'chromeos-base/chromeos-config-bsp-private/files/include',
      }
  }

  for program in ['reef', 'fizz']:
    _copy_baseboard(
        step_text='[%s] configuring public baseboard overlay' % program,
        src_path=path_cros_repo.joinpath(
            'src/overlays/baseboard-{}'.format(program),
            config_paths[program]['public_baseboard'],
        ),
        dst_path=path_cros_repo.joinpath(
            'src/overlays/overlay-{}'.format(program),
            config_paths[program]['public_overlay'],
        ),
    )

    _copy_baseboard(
        step_text='[%s] configuring private baseboard overlay' % program,
        src_path=path_cros_repo.joinpath(
            'src/private-overlays/baseboard-{}-private'.format(program),
            config_paths[program]['private_baseboard'],
        ),
        dst_path=path_cros_repo.joinpath(
            'src/private-overlays/overlay-{}-private'.format(program),
            config_paths[program]['private_overlay'],
        ),
    )


def create_download_payload(build):
  """Build a download payload.

  Args:
    build: a Build message with output properties

  Return:
    A BuildPayload if the Build message contains all the necessary
    information, otherwise None
  """
  if 'artifacts' not in build.output.properties:
    return None
  artifacts = build.output.properties['artifacts']
  if ('gs_bucket' not in artifacts or 'gs_path' not in artifacts or
      'files_by_artifact' not in artifacts):
    return None
  return BuildPayload(artifacts_gs_bucket=artifacts['gs_bucket'],
                      artifacts_gs_path=artifacts['gs_path'],
                      files_by_artifact=artifacts['files_by_artifact'])


def download_latest_config_yaml(api, builder_name):
  """Download latest project config.yaml from GS.

  Args:
    api: Reference to recipes API
    builder_name: the full name of the builder to search for

  Return:
    List containing the path where the downloaded config.yaml file resides,
    or empty list if no GS path was found for the builder.
  """

  with api.step.nest('download latest config yaml') as presentation:
    fields = frozenset({'output.properties'})
    predicate = builds_service_pb2.BuildPredicate(
        builder=builder_common_pb2.BuilderID(project='chromeos',
                                             bucket='postsubmit',
                                             builder=builder_name),
        tags=api.buildbucket.tags(relevance='relevant'), status='SUCCESS')
    rsp = api.buildbucket.search(predicate, limit=1, fields=fields)
    if len(rsp) == 0:
      presentation.step_text = 'No search results available from BuildBucket.search'
      return []
    payload = create_download_payload(rsp[0])
    if not payload:
      presentation.step_text = 'Unable to create download payload for config.yaml'
      return []
    try:
      return api.cros_artifacts.download_artifact(
          payload, BuilderConfig.Artifacts.CHROMEOS_CONFIG)
    except ValueError:
      presentation.step_text = 'Unable to download config.yaml'
      return []


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

    path_project_repo = path_cros_repo.joinpath('src/project/{}/{}'.format(
        config.program_name.lower(),
        config.project_name.lower(),
    ))

    path_config_yaml = None
    download_dirs = download_latest_config_yaml(
        api, '{}-postsubmit'.format(config.program_name.lower()))
    if len(download_dirs) > 0:
      path_config_yaml = download_dirs[0]

    path_imported = path_project_repo / 'imported'
    path_generated = path_project_repo / 'generated'

    path_public_yaml = None
    if config.public_yaml_path:
      path_public_yaml = path_cros_repo.joinpath(
          PATH_CROS_OVERLAYS,
          config.public_yaml_path,
      )

    path_private_yaml = None
    if config.HasField('private_yaml'):
      path_private_yaml = path_cros_repo.joinpath(
          PATH_CROS_OVERLAYS_PRIVATE,
          split_overlay_project(api, config.private_yaml.repo).split('/')[-1],
          config.private_yaml.path,
      )

    path_hwid = None
    if config.hwid_key:
      path_hwid = path_cros_repo.joinpath(
          PATH_CROS_HWID,
          'v3/{}'.format(config.hwid_key),
      )

    with api.context(cwd=path_project_repo):
      # Create import directory.
      api.file.ensure_directory(
          'ensure %s directory exists' % path_imported,
          path_imported,
      )

      # Copy public model.yaml to import.
      if path_public_yaml:
        dst_path = path_imported / 'public_model.yaml'
        api.file.copy(
            'copy public model.yaml',
            path_public_yaml,
            dst_path,
        )
        api.git.add([dst_path])

      # Copy private model.yaml to import.
      if path_private_yaml:
        dst_path = path_imported / 'private_model.yaml'
        api.file.copy(
            'copy private model.yaml',
            path_private_yaml,
            dst_path,
        )
        api.git.add([dst_path])

      # Copy the HWID database.
      if config.hwid_key:
        dst_path = path_imported / 'hwid'
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
      path_config_bundle = path_generated / 'config.jsonproto'
      api.path.mock_add_paths(path_config_bundle)

      # Merge backfilled data into a ConfigBundle payload
      cmd = [path_cros_repo.joinpath(PATH_CROS_CONFIG, JOIN_SCRIPT_PATH)]
      cmd += ['--log', 'DEBUG']
      cmd += ['--project-name', config.project_name]
      cmd += ['--program-name', config.program_name]

      if path_config_yaml:
        if path_public_yaml:
          cmd += ['--public-model', path_config_yaml]
      else:
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
        path_imported_config = path_generated / 'imported.jsonproto'
        api.step('Generate imported configuration', [
            'vpython3',
            '-vpython-spec',
            path_cros_repo.joinpath(PATH_CROS_CONFIG, '.vpython'),
            '-vpython-log-level',
            'info',
        ] + cmd + [
            '--import-only',
            '--output',
            path_imported_config,
        ])
        api.git.add([path_imported_config])

        # generate joined config (with merging)
        path_merged_config = path_generated / 'joined.jsonproto'
        api.step('Generate joined configuration', [
            'vpython3',
            '-vpython-spec',
            path_cros_repo.joinpath(PATH_CROS_CONFIG, '.vpython'),
            '-vpython-log-level',
            'info',
        ] + cmd + [
            '--output',
            path_merged_config,
        ])
        api.git.add([path_merged_config])

    # Commit changes (if any)
    with api.step.nest('diffing repo to find changes'):
      changed_files = api.git.get_diff_files('HEAD')
      if changed_files:
        step_pres.logs['changed files'] = ', '.join(changed_files)
      else:
        step_pres.step_summary_text = 'no files changed'
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


def backfill_project(api, config):
  """Backfill an individual project.

  Expects to be run in the root of the chromeos checkout.

  Args:
    config (ConfigBackfillProperties.ProjectConfig) - configuration for project

  Return:
    BackfillStatus with results of backfill.  commit hash if empty if no commit
    is made.
  """

  program = config.program_name.lower()
  project = config.project_name.lower()

  path_cros_repo = api.context.cwd
  path_project_repo = path_cros_repo.joinpath('src/project/{}/{}'.format(
      program, project))

  with api.step.nest('processing {}/{}'.format(program,
                                               project)) as presentation:
    if not api.path.exists(path_project_repo):
      presentation.step_summary_text = 'not checked out'
      return BackfillStatus(True, program, project, '')

    # Update the repo atomically
    with api.context(cwd=path_project_repo):
      infos = api.repo.project_infos(
          projects=[api.context.cwd],
          ignore_missing=True,
      )

      if not infos:
        presentation.step_summary_text = 'not in manifest'
        return BackfillStatus(True, program, project, '')

      project_info = infos[0]
      updated = api.git_txn.update_ref(
          project_info.remote,
          config_merger(api, config, path_cros_repo, presentation),
          ref=project_info.branch,
          dry_run=api.cros_infra_config.is_staging,
      )

      commit_hash = ''
      if updated:
        commit_hash = api.git.head_commit()

        # don't actually link to commit in staging (because it doesn't exist)
        if api.cros_infra_config.is_staging:
          presentation.step_summary_text = '[%s]' % commit_hash[:8]
        else:
          url = api.git.remote_url(project_info.remote) + '/+/' + commit_hash
          presentation.step_summary_text = '[%s](%s)' % (commit_hash[:8], url)

      return BackfillStatus(False, program, project, commit_hash)


def format_output_markdown(commits, errors, nmissing):
  """Generate markdown to be shown for the build status.

  Args:
    commits: list of (program, project, hash) values for commits
    errors: list of string-formattable errors
    nmissing: number of projects missing from manifest

  Return:
    Formatted markdown string suitable to return via RawResult proto.
  """

  # create summary markdown
  COMMIT_TEMPLATE = \
    '- {program}/{project} [{commit_short}]('                      \
      'https://chrome-internal.googlesource.com/chromeos/project/' \
      '{program}/{project}/+/{commit_sha}'                         \
    ')'

  lines = ['']
  if commits:
    lines = ['{} changes made'.format(len(commits))]
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
    lines.append('')

  if errors:
    lines.append('{} errors'.format(len(errors)))
    for error in errors:
      lines.append('- {}'.format(error))
    lines.append('')

  if nmissing > 0:
    lines.append('{} missing from manifest'.format(nmissing))

  # Truncate the list of failures per section to keep the summary under
  # Buildbucket's 4000 byte limit on the summary_markdown field.
  markdown = lines[0]
  for line in lines[1:]:
    if len(markdown) + len(line) < 3990:
      markdown += '\n\n' + line
    else:  # pragma: nocover
      # Abruptly truncate to avoid INFRA_FAILURE.
      markdown += '\n\n...'
      break

  return markdown


def RunSteps(api, properties):
  api.cros_source.configure_builder(default_main=True)

  # setup overlays, sync projects and move to tip-of-tree
  with api.cros_source.checkout_overlays_context():
    api.cros_source.ensure_synced_cache()

    with api.context(cwd=api.cros_source.workspace_path):
      with api.step.nest('create portage workaround symlinks'):
        create_portage_workaround(api)

      # run backfill
      futures = [
          api.futures.spawn(backfill_project, api, config)
          for config in properties.configs
      ]
      api.futures.wait(futures)

      # parse results
      nmissing = 0
      output_commits = collections.defaultdict(dict)
      commits = []
      errors = []
      for f in futures:
        ex = f.exception()
        if ex:
          errors.append(ex)
          continue

        result = f.result()
        missing, program, project, commit = result

        if commit:
          commits.append((program, project, commit))

        if missing:
          nmissing += 1
        else:
          if commit:
            output_commits[program][project] = commit

      # save results in output properties
      api.easy.set_properties_step(commits=output_commits)

      return result_pb2.RawResult(
          status=common_pb2.FAILURE if errors else common_pb2.SUCCESS,
          summary_markdown=format_output_markdown(
              commits,
              errors,
              nmissing,
          ),
      )


def GenTests(api):

  def mock_workspace_path(path):
    return api.path.exists(api.src_state.workspace_path / path)

  def generate_mock_build(include_artifacts=True, include_config_yaml=True,
                          include_gs_bucket=True):
    """Generate a mock BuildBucket search build result.

    Use the arguments to generate different result corner cases.

    Args:
      include_artifacts: boolean
      include_config_yaml: boolean
      include_gs_bucket: boolean
    """
    files = {'EBUILD_LOGS': ['ebuild_logs.tar.gz']}
    if include_config_yaml:
      files['CHROMEOS_CONFIG'] = ['config.yaml']
    artifacts = {'gs_path': 'custom/image-path-123', 'files_by_artifact': files}
    if include_gs_bucket:
      artifacts['gs_bucket'] = 'chromeos-image-archive'
    properties = {}
    if include_artifacts:
      properties = {'artifacts': artifacts}
    output = build_pb2.Build.Output()
    output.properties.update(properties)
    r = []
    r.append(
        build_pb2.Build(id=1234, builder={'builder': 'mybuilder-postsubmit'},
                        status=common_pb2.SUCCESS, output=output))
    return r

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
      mock_workspace_path('src/project/test_program/test_project'),
  )

  yield api.test(
      'basic-staging',
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
      mock_workspace_path('src/project/test_program/test_project'),
  )

  yield api.test(
      'backfill-error',
      api.properties(
          **{
              'configs': [{
                  'public_yaml_path': 'some/model.yaml',
                  'private_yaml': {
                      'repo': CROS_INTERNAL + '/private/',
                      'path': 'some/model.yaml'
                  },
                  'hwid_key': 'some_key',
                  'project_name': 'test_project',
                  'program_name': 'test_program',
              }]
          }),
      api.step_data(
          'processing test_program/test_project'
          '.update ref.git transaction'
          '.Generate imported configuration', retcode=1),
      mock_workspace_path('src/project/test_program/test_project'),
      status='FAILURE',
  )

  yield api.test(
      'buildbucket-search-result',
      api.buildbucket.generic_build(builder='staging-backfiller'),
      api.properties(
          **{
              'configs': [{
                  'public_yaml_path': 'some/model.yaml',
                  'private_yaml': {
                      'repo': CROS_INTERNAL + '/private/',
                      'path': 'some/model.yaml'
                  },
                  'hwid_key': 'some_key',
                  'project_name': 'test_project',
                  'program_name': 'test_program',
              }]
          }),
      mock_workspace_path('src/project/test_program/test_project'),
      api.buildbucket.simulated_search_results(
          generate_mock_build(include_config_yaml=True),
          'processing test_program/test_project'
          '.update ref.git transaction'
          '.download latest config yaml.buildbucket.search'),
      api.post_process(
          post_process.StepCommandContains,
          'processing test_program/test_project'
          '.update ref.git transaction'
          '.download latest config yaml'
          '.download CHROMEOS_CONFIG.gsutil download',
          [
              'cp',
              'gs://chromeos-image-archive/custom/image-path-123/config.yaml'
          ],
      ),
  )

  yield api.test(
      'no-buildbucket-search-result',
      api.buildbucket.generic_build(builder='staging-backfiller'),
      api.properties(
          **{
              'configs': [{
                  'public_yaml_path': 'some/model.yaml',
                  'private_yaml': {
                      'repo': CROS_INTERNAL + '/private/',
                      'path': 'some/model.yaml'
                  },
                  'hwid_key': 'some_key',
                  'project_name': 'test_project',
                  'program_name': 'test_program',
              }]
          }),
      mock_workspace_path('src/project/test_program/test_project'),
      api.buildbucket.simulated_search_results(
          generate_mock_build(include_config_yaml=False),
          'processing test_program/test_project'
          '.update ref.git transaction'
          '.download latest config yaml.buildbucket.search'),
  )

  yield api.test(
      'incomplete-buildbucket-search-result',
      api.buildbucket.generic_build(builder='staging-backfiller'),
      api.properties(
          **{
              'configs': [{
                  'public_yaml_path': 'some/model.yaml',
                  'private_yaml': {
                      'repo': CROS_INTERNAL + '/private/',
                      'path': 'some/model.yaml'
                  },
                  'hwid_key': 'some_key',
                  'project_name': 'test_project',
                  'program_name': 'test_program',
              }]
          }),
      mock_workspace_path('src/project/test_program/test_project'),
      api.buildbucket.simulated_search_results(
          generate_mock_build(include_gs_bucket=False),
          'processing test_program/test_project'
          '.update ref.git transaction'
          '.download latest config yaml.buildbucket.search'),
  )

  yield api.test(
      'no-buildbucket-artifacts-search-result',
      api.buildbucket.generic_build(builder='staging-backfiller'),
      api.properties(
          **{
              'configs': [{
                  'public_yaml_path': 'some/model.yaml',
                  'private_yaml': {
                      'repo': CROS_INTERNAL + '/private/',
                      'path': 'some/model.yaml'
                  },
                  'hwid_key': 'some_key',
                  'project_name': 'test_project',
                  'program_name': 'test_program',
              }]
          }),
      mock_workspace_path('src/project/test_program/test_project'),
      api.buildbucket.simulated_search_results(
          generate_mock_build(include_artifacts=False),
          'processing test_program/test_project'
          '.update ref.git transaction'
          '.download latest config yaml.buildbucket.search'),
  )

  yield api.test(
      'staging-no-commit',
      api.buildbucket.generic_build(builder='staging-backfiller'),
      api.properties(
          **{
              'configs': [{
                  'public_yaml_path': 'some/model.yaml',
                  'private_yaml': {
                      'repo': CROS_INTERNAL + '/private/',
                      'path': 'some/model.yaml'
                  },
                  'hwid_key': 'some_key',
                  'project_name': 'test_project',
                  'program_name': 'test_program',
              }]
          }),
      mock_workspace_path('src/project/test_program/test_project'),
      api.post_process(
          post_process.StepCommandContains,
          'processing test_program/test_project'
          '.update ref.git transaction'
          '.git push',
          ['git', 'push', '--dry-run'],
      ),
  )

  yield api.test(
      'not-in-manifest',
      api.properties(
          **{
              'configs': [{
                  'public_yaml_path': 'some/model.yaml',
                  'private_yaml': {
                      'repo': CROS_INTERNAL + '/private/',
                      'path': 'some/model.yaml'
                  },
                  'hwid_key': 'some_key',
                  'project_name': 'test_project',
                  'program_name': 'test_program',
              }]
          }),
      mock_workspace_path('src/project/test_program/test_project'),
      api.step_data(
          'processing test_program/test_project.repo forall',
          stdout=api.raw_io.output_text(''),
      ),
      api.post_process(
          post_process.StepSummaryEquals,
          'processing test_program/test_project',
          'not in manifest',
      ),
  )

  yield api.test(
      'not-checked-out',
      api.properties(
          **{
              'configs': [{
                  'public_yaml_path': 'some/model.yaml',
                  'private_yaml': {
                      'repo': CROS_INTERNAL + '/private/',
                      'path': 'some/model.yaml'
                  },
                  'hwid_key': 'some_key',
                  'project_name': 'test_project',
                  'program_name': 'test_program',
              }]
          }),
      api.post_process(
          post_process.StepSummaryEquals,
          'processing test_program/test_project',
          'not checked out',
      ),
  )

  yield api.test(
      'no-changed-files',
      api.properties(
          **{
              'configs': [{
                  'public_yaml_path': 'some/model.yaml',
                  'private_yaml': {
                      'repo': CROS_INTERNAL + '/private/',
                      'path': 'some/model.yaml'
                  },
                  'hwid_key': 'some_key',
                  'project_name': 'test_project',
                  'program_name': 'test_program',
              }]
          }),
      mock_workspace_path('src/project/test_program/test_project'),
      api.step_data(
          'processing test_program/test_project'
          '.update ref.git transaction'
          '.diffing repo to find changes.git diff',
          stdout=api.raw_io.output_text('')),
  )

  yield api.test(
      'changed-files',
      api.properties(
          **{
              'configs': [{
                  'public_yaml_path': 'some/model.yaml',
                  'private_yaml': {
                      'repo': CROS_INTERNAL + '/private/',
                      'path': 'some/model.yaml'
                  },
                  'hwid_key': 'some_key',
                  'project_name': 'test_project',
                  'program_name': 'test_program',
              }]
          }),
      mock_workspace_path('src/project/test_program/test_project'),
      api.step_data(
          'processing test_program/test_project'
          '.update ref.git transaction'
          '.diffing repo to find changes.git diff',
          stdout=api.raw_io.output_text('dfdsaf')),
      api.step_data(
          'processing test_program/test_project.update ref.git transaction'
          '.git push', stdout=api.raw_io.output_text(
              ('remote:   https://example.com/c/some/project/repo/+/123 '
               'config_backfill: test'))),
  )
