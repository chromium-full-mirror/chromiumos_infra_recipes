# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating ChromeOS source cache snapshots."""

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_engine import result as result_pb2
from PB.recipe_modules.chromeos.gcloud.gcloud import SourceCacheAction
from PB.recipes.chromeos.source_cache_builder import (
    SourceCacheBuilderProperties)
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/futures',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/scheduler',
    'recipe_engine/step',
    'depot_tools/depot_tools',
    'chrome',
    'cros_cache',
    'cros_infra_config',
    'cros_release',
    'easy',
    'failures',
    'gcloud',
    'git',
    'repo',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = SourceCacheBuilderProperties


def _determine_if_full_sync(api: RecipeApi, fsm: int) -> bool:
  """Inspect the trigger properties to determine if we full sync."""
  with api.step.nest('determine if full sync') as pres:
    if fsm == 0:
      pres.step_text = 'full_sync_modulo not set, never full syncing'
      return False

    cron_triggers = [
        x for x in api.scheduler.triggers if x.WhichOneof('payload') == 'cron'
    ]
    if cron_triggers:
      last_trig = sorted([x.cron.generation for x in cron_triggers])[-1]
      pres.step_text = 'cron generation id {} % {} '.format(last_trig, fsm)
      if last_trig % fsm == 0:
        pres.step_text += '== 0, doing full sync'
        return True
      pres.step_text += '!= 0, not doing full sync'
      return False
    pres.step_text = 'no cron triggers, not doing full sync'
    return False


def RunSteps(api: RecipeApi, properties: SourceCacheBuilderProperties):
  full_sync = _determine_if_full_sync(api, properties.full_sync_modulo)
  api.easy.set_properties_step(full_sync=full_sync)
  if full_sync:
    api.gcloud.cache_action = SourceCacheAction.DONT_MOUNT_ANY_CACHE

  with api.step.nest('source cache update'):
    snapshot_prefixes = []
    image_prefixes = []
    step_failures = []
    is_staging = api.cros_infra_config.is_staging
    infra_host = api.gcloud.infra_host
    for cache in properties.cache_definition:
      successful_sync = False
      api.gcloud.setup_cache_disk(cache_name=cache.cache_name,
                                  branch=cache.branch,
                                  disk_type=cache.disk_type, recipe_mount=True,
                                  disallow_previously_mounted=True,
                                  recovery_snapshot=cache.recovery_snapshot)
      snapshot_prefix = '{}-{}'.format(cache.cache_name, api.gcloud.branch)
      if is_staging:
        snapshot_prefix = 'staging-{}'.format(snapshot_prefix)
      snapshot_prefixes.append(snapshot_prefix)
      image_prefixes.append(snapshot_prefix)
      with api.step.nest('sync mounted cache directories'):
        snapshot_name = '{}-{}'.format(snapshot_prefix,
                                       api.gcloud.snapshot_suffix)
        snapshot_name = snapshot_name[:api.gcloud.gce_name_limit] if len(
            snapshot_name) > api.gcloud.gce_name_limit else snapshot_name
        disk = api.gcloud.gce_disk
        mount_path = api.gcloud.snapshot_builder_mount_path.join(
            cache.cache_name)
        try:
          if cache.command == 'repo':
            with api.context(cwd=mount_path):
              sync_opts = dict(force_sync=True, detach=True, jobs=20,
                               retry_fetches=8, timeout=10800,
                               force_remove_dirty=True, prune=True)
              manifest_branch = '{}snapshot'.format(
                  'staging-' if is_staging else '')
              if cache.branch != 'main':
                manifest_branch = cache.branch
              init_opts = dict(verbose=True, manifest_branch=manifest_branch)
              manifest_url = (
                  api.src_state.external_manifest.url if cache.external_source
                  else api.src_state.internal_manifest.url)
              api.repo.ensure_synced_checkout(mount_path, manifest_url,
                                              init_opts=init_opts,
                                              sync_opts=sync_opts,
                                              final_cleanup=True, sanitize=True)
              manifest_dir = 'manifest-versions-internal'
              manifest_path = mount_path.join(manifest_dir)
              api.path.mock_add_paths(manifest_path)
              if api.path.exists(manifest_path):
                api.file.rmtree(
                    'Removing previous directory {}'.format(manifest_path),
                    manifest_path)
              if not cache.external_source:
                with api.step.nest('git clone manifest-versions'):
                  api.git.clone(repo_url=api.cros_release.MANIFEST_VERSIONS_URL,
                                target_path=manifest_dir)
          if cache.command == 'gclient':
            # Chrome cache consists of a local repo cache and src,
            # both mounted via a single disk. We change into the
            # source directory to sync.
            api.chrome.cache_sync(cache_path=mount_path)
          successful_sync = True
        # If sync fails, write a recovery image to the current version file.
        except StepFailure as e:
          api.cros_cache.write_and_upload_version(
              properties.cache_bucket, api.gcloud.snapshot_version_file,
              cache.recovery_snapshot)
          step_failures.append(e)
      with api.step.nest('sync disk cache before imaging'):
        api.gcloud.sync_disk_cache(name=api.gcloud.disk_short_name)
      with api.step.nest('unmount disk for imaging'):
        api.gcloud.unmount_disk(name=cache.cache_name, mount_path=mount_path)
      with api.step.nest('detach disk for imaging'):
        api.gcloud.detach_disk(instance=infra_host, disk=disk,
                               zone=api.gcloud.host_zone)
      if successful_sync:
        with api.step.nest('create image from disk'):
          api.gcloud.create_image_from_disk(disk=disk, image_name=snapshot_name,
                                            zone=api.gcloud.host_zone)
        with api.step.nest('upload updated version file'):
          api.cros_cache.write_and_upload_version(
              properties.cache_bucket, api.gcloud.snapshot_version_file,
              snapshot_name)
      with api.step.nest('delete disk'):
        api.gcloud.delete_disk(disk=disk, zone=api.gcloud.host_zone)
  with api.step.nest('cleanup expired images'):
    image_delete_list = api.gcloud.get_expired_images(
        retention_days=properties.retention_days, prefixes=image_prefixes,
        protected_images=properties.protected_images)
    api.easy.set_properties_step(expired_images=image_delete_list)
    api.gcloud.delete_images(images=image_delete_list)
  with api.step.nest('delete orphaned disks'):
    disks_to_delete = api.gcloud.determine_disks_to_delete(
        disks=api.gcloud.list_all_disks(),
        instances=api.gcloud.list_all_instances())
    api.easy.set_properties_step(orphaned_disks=disks_to_delete)
    if not is_staging:
      futures = []
      # We need to sort to make the test results deterministic
      for disk, zone in [
          (d, disks_to_delete[d]) for d in sorted(disks_to_delete.keys())
      ]:
        futures.append(
            api.futures.spawn(api.gcloud.delete_disk, disk=disk, zone=zone))
      api.futures.wait(futures)
  # return RawResult directly to set the markdown (only with luciexe)
  return result_pb2.RawResult(
      status=common_pb2.FAILURE if step_failures else common_pb2.SUCCESS,
      summary_markdown=api.failures.format_step_failures(
          step_failures=step_failures))


def GenTests(api: RecipeTestApi):

  yield api.test('basic')

  yield api.test(
      'attach-chromeos-disk',
      api.properties(
          cache_definition=[
              dict(
                  cache_name='chromiumos',
                  command='repo',
                  recovery_snapshot='chromeos_default_recovery_snapshot',
                  branch='release-R90-13816.B',
                  disk_type='pd-ssd',
              ),
          ],
          cache_bucket='chromeos-bot-cache',
          retention_days=7,
          protected_snapshots=['staging-chromeos-cache-snapshot-1625886728983'],
      ))

  yield api.test(
      'staging-execution',
      api.buildbucket.generic_build(builder="staging_SourceCacheBuilder",
                                    bucket='staging'),
      api.properties(
          cache_definition=[
              dict(
                  cache_name='chromiumos',
                  command='repo',
                  recovery_snapshot='chromeos_default_recovery_snapshot',
                  branch='main',
                  disk_type='pd-ssd',
              ),
              dict(
                  cache_name='chromeos',
                  command='repo',
                  recovery_snapshot='chromeos_default_recovery_snapshot',
                  branch='main',
                  disk_type='pd-ssd',
              ),
          ],
          cache_bucket='chromeos-bot-cache',
          retention_days=7,
          protected_snapshots=['staging-chromeos-cache-snapshot-1625886728983'],
      ))

  yield api.test(
      'sync-caches',
      api.properties(
          cache_definition=[
              dict(
                  cache_name='chromeos',
                  command='repo',
                  recovery_snapshot='chromeos_default_recovery_snapshot',
                  branch='main',
                  disk_type='pd-ssd',
              ),
              dict(
                  cache_name='chrome',
                  command='gclient',
                  recovery_snapshot='chrome_default_recovery_snapshot',
                  branch='main',
                  disk_type='pd-ssd',
              ),
              dict(
                  cache_name='chromiumos',
                  command='repo',
                  recovery_snapshot='chromiumos_default_recovery_snapshot',
                  branch='main',
                  disk_type='pd-ssd',
                  external_source=True,
              ),
          ],
          cache_bucket='chromeos-bot-cache',
          retention_days=7,
          protected_snapshots=['staging-chromeos-cache-snapshot-1625886728983'],
      ))

  yield api.test(
      'sync-cache-step-failure',
      api.properties(
          cache_definition=[
              dict(
                  cache_name='chromiumos',
                  command='repo',
                  recovery_snapshot='chromeos_default_recovery_snapshot',
                  branch='main',
                  disk_type='pd-ssd',
              ),
          ],
          cache_bucket='chromeos-bot-cache',
          retention_days=7,
          protected_snapshots=['staging-chromeos-cache-snapshot-1625886728983'],
      ),
      api.step_data((
          'source cache update.sync mounted cache directories.Write proto to [CLEANUP]/snapshot/chromiumos/.recipes_state.json (2)'
      ), retcode=3),
  )

  yield api.test(
      'full-sync-modulo-false',
      api.properties(
          cache_definition=[
              dict(
                  cache_name='chromiumos',
                  command='repo',
                  recovery_snapshot='chromeos_default_recovery_snapshot',
                  branch='main',
                  disk_type='pd-ssd',
              ),
          ],
          cache_bucket='chromeos-bot-cache',
          retention_days=7,
          protected_snapshots=['staging-chromeos-cache-snapshot-1625886728983'],
          full_sync_modulo=1337,  # Not going to match this modulo.
      ),
      api.properties(
          **{
              '$recipe_engine/scheduler': {
                  "hostname":
                      "luci-scheduler.appspot.com",
                  "invocation":
                      "8967204358994338640",
                  "job":
                      "chromeos/staging_SourceCacheBuilder",
                  "triggers": [
                      {
                          "cron": {
                              "generation": "1335"
                          },
                          "id": "cron:v1:1335"
                      },
                      {
                          "webui": {},  # Here we add an unassociated trigger.
                      },
                      {
                          "cron": {
                              "generation": "1336"
                          },
                          "id": "cron:v1:1336"
                      }
                  ]
              }
          }),
      api.post_check(post_process.DoesNotRunRE,
                     r'.+create disk with empty checkout$'))

  yield api.test(
      'full-sync-modulo-true',
      api.properties(
          cache_definition=[
              dict(
                  cache_name='chromiumos',
                  command='repo',
                  recovery_snapshot='chromeos_default_recovery_snapshot',
                  branch='main',
                  disk_type='pd-ssd',
              ),
          ],
          cache_bucket='chromeos-bot-cache',
          retention_days=7,
          protected_snapshots=['staging-chromeos-cache-snapshot-1625886728983'],
          full_sync_modulo=1,  # Always full sync when mod == 1.
      ),
      api.properties(
          **{
              '$recipe_engine/scheduler': {
                  "hostname":
                      "luci-scheduler.appspot.com",
                  "invocation":
                      "8967204358994338640",
                  "job":
                      "chromeos/staging_SourceCacheBuilder",
                  "triggers": [{
                      "cron": {
                          "generation": "15221"
                      },
                      "id": "cron:v1:15221"
                  }, {
                      "cron": {
                          "generation": "15224"
                      },
                      "id": "cron:v1:15224"
                  }]
              }
          }),
      api.post_check(post_process.MustRunRE,
                     r'.+create disk with empty checkout$'))

  yield api.test(
      'full-sync-modulo-no-trigger',
      api.properties(
          cache_definition=[
              dict(
                  cache_name='chromiumos',
                  command='repo',
                  recovery_snapshot='chromeos_default_recovery_snapshot',
                  branch='main',
                  disk_type='pd-ssd',
              ),
          ],
          cache_bucket='chromeos-bot-cache',
          retention_days=7,
          protected_snapshots=['staging-chromeos-cache-snapshot-1625886728983'],
          full_sync_modulo=1,  # Always full sync when mod == 1.
      ),
      api.post_check(post_process.DoesNotRunRE,
                     r'.+create disk with empty checkout$'))

  yield api.test(
      'full-sync-modulo-unspecified',
      api.properties(
          cache_definition=[
              dict(
                  cache_name='chromiumos',
                  command='repo',
                  recovery_snapshot='chromeos_default_recovery_snapshot',
                  branch='main',
                  disk_type='pd-ssd',
              ),
          ],
          cache_bucket='chromeos-bot-cache',
          retention_days=7,
          protected_snapshots=['staging-chromeos-cache-snapshot-1625886728983'],
          full_sync_modulo=0,  # Full sync unspecified (default proto val == 0).
      ),
      api.properties(
          **{
              '$recipe_engine/scheduler': {
                  "hostname":
                      "luci-scheduler.appspot.com",
                  "invocation":
                      "8967204358994338640",
                  "job":
                      "chromeos/staging_SourceCacheBuilder",
                  "triggers": [{
                      "cron": {
                          "generation": "15221"
                      },
                      "id": "cron:v1:15221"
                  }, {
                      "cron": {
                          "generation": "15224"
                      },
                      "id": "cron:v1:15224"
                  }]
              }
          }),
      api.post_check(post_process.DoesNotRunRE,
                     r'.+create disk with empty checkout$'))
