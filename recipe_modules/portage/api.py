# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs for CrOS Portage."""

from collections import defaultdict
from datetime import datetime, timedelta
import os
import re

from recipe_engine import recipe_api


class PortageApi(recipe_api.RecipeApi):
  """A module for CrOS Portage steps."""

  def initialize(self):
    # Default dict of [step_name][emerge_type] -> count.
    self._portage_emerge_stats = {}

    self._BQ_TABLE_NAME = 'portage_stats.staging' if self.m.cros_infra_config.is_staging else 'portage_stats.prod'

    self._INSERT_QUERY_FORMAT = '''INSERT `chromeos-bot.{dataset}` (job, total,
    category, package, version, duration, start, `end`, insert_time, emerge_type,
    bbid, bucket, builder, step_name)
    SELECT * FROM UNNEST([{query_data}])'''

    self._INSERT_QUERY_DATA = '''(%(job)s,
    %(total)s,
    '%(category)s',
    '%(package)s',
    '%(version)s',
    %(duration)s,
    DATETIME('%(start)s'),
    DATETIME('%(end)s'),
    DATETIME('%(insert_time)s'),
    '%(emerge_type)s',
    '%(bbid)s',
    '%(bucket)s',
    '%(builder)s',
    '%(step_name)s')'''

    # Many of these regexs can be best understood by consulting `man emerge`.
    self._START_STATES = ['Emerging binary', 'Emerging']
    self._END_STATES = ['Completed', 'Failed to emerge']

    self._TIME_PART = r'(?P<time>[\d:\.]+) '
    self._STATE_PART = r'(?P<state>({})) '.format('|'.join(self._START_STATES +
                                                           self._END_STATES))
    self._ORDER_PART = r'(\((?P<job>\d+) of (?P<total>\d+)\) )?'
    self._PACKAGE_PART = r'(?P<category>(\w|-|^\/)+)\/(?P<package>[\w][\w+-]*)-'
    self._VERSION_PART = r'(?P<version>(\d+)((\.\d+)*)([a-z]?)((_(pre|p|beta|alpha|rc)\d*)*)(-r(\d+))?)'
    self._PORTAGE_PROGRESS_PREFIX = r'^>>> '

    self._DURATION_REGEX = re.compile(self._PORTAGE_PROGRESS_PREFIX +
                                      self._TIME_PART + self._STATE_PART +
                                      self._ORDER_PART + self._PACKAGE_PART +
                                      self._VERSION_PART)
    self._PORTAGE_EMERGE_TYPE_RE = re.compile(
        r'^\[(?P<emerge_type>\w+)[ NSUDrRFfIBb#*~]{1,12}\] ' +
        self._PACKAGE_PART + self._VERSION_PART)
    self._INFO_RUN_START_RE = re.compile(
        self._TIME_PART + r'INFO\s+: Running: (?P<command>[\/\w\.]*)')
    self._INFO_RUN_END_RE = re.compile(
        self._TIME_PART + r'INFO\s+: Elapsed time \((?P<command>.+)\)')

  def publish_emerge_stats(self, step_name: str, step_stdout: str,
                           set_output_prop: bool = False,
                           publish_to_bq: bool = False) -> dict:
    """Reads portage stdout and tries to glean facts about emerge performance.

    Portage gives us a stdout stream and outputs a formatted representation of
    number of packages that it will emerge, and the method in which it will
    emerge them. In lieu of a _good_ system (formatted output, bapi response,
    etc) we can sniff through this stdout and gather facts about prebuilt use,
    among other things. We produce an output property keyed on the provided
    step_name.

    Args:
      step_name: A unique step name (e.g. the bapi's step) and will be used
          as the output key in the metrics dictionary.
      step_stdout: The full standard out for the bapi call.
      set_output_prop: Should we set an output property with the results of
          the text analysis. Be mindful, it maybe quite large.
      publish_to_bq: Should we publish to the configured 'portage_stats'
          dataset.

    Returns:
      The current value of the output property.
    """

    def _soft_fail(msg):
      self.m.easy.set_properties_step('set failed portage stats',
                                      failed_portage_stats=True)
      pres.step_text = 'Soft failure finding portage stats -- {}'.format(msg)

    def _get_key(group_dict):
      return '|'.join([
          group_dict['category'], group_dict['package'], group_dict['version']
      ])

    def _parse_time(time_str):
      try:
        return datetime.strptime(time_str, '%H:%M:%S.%f')
      except ValueError:
        # Will reraise if we still can't parse it.
        return datetime.strptime(time_str, '%H:%M:%S')

    # Gathering/setting these metrics shouldn't be allowed to fail the build.
    with self.m.step.nest('adding emerge metrics') as pres:
      try:
        # seen are the packages that we've noticed in the output.
        # ready have seen enough about a package to be 'complete'.
        seen, ready = defaultdict(list), []

        # Keep a consistent insert time.
        insert_time = self.m.time.utcnow()

        # Pass one, look at the durations.
        lines = step_stdout.splitlines()
        for line in lines:
          # Usually first in the logs.
          if self._PORTAGE_EMERGE_TYPE_RE.match(line):
            group_dict = self._PORTAGE_EMERGE_TYPE_RE.search(line).groupdict()
            key = _get_key(group_dict)

            # If we see a package again, we didn't properly close the last one.
            if key in seen:
              del seen[key]
              _soft_fail('unclosed package: {}'.format(key))
            else:
              # Initialize the seen entry with this group_dict's contents..
              seen[key].append(group_dict)

          elif self._DURATION_REGEX.match(line):
            group_dict = self._DURATION_REGEX.search(line).groupdict()
            key = _get_key(group_dict)
            # Only process packages that have seen _PORTAGE_EMERGE_TYPE
            if key not in seen:
              continue
            seen[key].append(group_dict)

            # Have an emerge type, start, and a stop, thus process and pop.
            if len(seen[key]) == 3:
              similar_list = seen[key]
              emerge_entry = similar_list[0]
              start_entry = similar_list[1]
              end_entry = similar_list[2]

              start = _parse_time(start_entry['time'])
              end = _parse_time(end_entry['time'])

              # if end < start, assume we started a day ago.
              if end < start:
                start -= timedelta(days=1)
              total_duration = end - start

              # Add additional info to the start of compile dict and push
              # to the ready array.
              result = similar_list[1]
              result['start'] = str(start)
              result['end'] = str(end)
              result['duration'] = int(total_duration /
                                       timedelta(milliseconds=1))
              result['insert_time'] = str(insert_time)
              result['emerge_type'] = emerge_entry['emerge_type']
              result['bbid'] = self.m.buildbucket.build.id
              result['bucket'] = self.m.buildbucket.build.builder.bucket
              result['builder'] = self.m.buildbucket.build.builder.builder
              result['step_name'] = step_name
              result.pop('state')
              result.pop('time')
              # Add to completed results and remove the key (so future emerges
              # can use the same key).
              ready.append(result)
              del seen[key]
          elif self._INFO_RUN_START_RE.match(line):
            group_dir = self._INFO_RUN_START_RE.search(line).groupdict()
            cmd = os.path.basename(group_dir['command'])
            if cmd == 'sudo':
              continue
            seen[cmd].append(group_dir)
          elif self._INFO_RUN_END_RE.match(line):
            group_dir = self._INFO_RUN_END_RE.search(line).groupdict()
            cmd = os.path.basename(group_dir['command'])
            if cmd not in seen:
              continue
            seen[cmd].append(group_dir)
            if len(seen[cmd]) == 2:
              similar_list = seen[cmd]
              start_entry = similar_list[0]
              end_entry = similar_list[1]
              start = _parse_time(start_entry['time'])
              end = _parse_time(end_entry['time'])
              total_duration = end - start

              result = similar_list[1]
              result['job'] = '0'
              result['total'] = '1'
              result['category'] = 'info_run'
              result['package'] = cmd
              result['version'] = '1.0'
              result['start'] = str(start)
              result['end'] = str(end)
              result['duration'] = int(total_duration /
                                       timedelta(milliseconds=1))
              result['insert_time'] = str(insert_time)
              result['emerge_type'] = 'binary'
              result['bbid'] = self.m.buildbucket.build.id
              result['bucket'] = self.m.buildbucket.build.builder.bucket
              result['builder'] = self.m.buildbucket.build.builder.builder
              result['step_name'] = step_name
              result.pop('time')
              result.pop('command')
              # Add completed result
              ready.append(result)
              del seen[cmd]

        if seen:
          # TODO(b/266749698): Catch packages that are not outputting emerge
          # method. These should be relatively rare and not the bulk of runtime.
          _soft_fail('unclosed packages')

        if ready:
          # Set the internal tracked dict.
          self._portage_emerge_stats[step_name] = ready

          if set_output_prop:
            # Set the internal running copy and set the output prop.
            self.m.easy.set_properties_step(
                'set portage stats', portage_stats=self._portage_emerge_stats)
          if publish_to_bq:
            # Do the BQ insert.
            query_data = ',\n'.join(
                [self._INSERT_QUERY_DATA % x for x in ready])
            whole_query = self._INSERT_QUERY_FORMAT.format(
                dataset=self._BQ_TABLE_NAME, query_data=query_data)
            self.m.step('insert to bq',
                        ['bq', 'query', '--use_legacy_sql=false'],
                        stdin=self.m.raw_io.input_text(whole_query), timeout=60)

      except Exception as e:  # pylint: disable=broad-except
        self.m.easy.set_properties_step('set failed portage stats',
                                        failed_portage_stats=True)
        pres.status = self.m.step.SUCCESS
        pres.step_text = 'Failure to publish portage stats'
        pres.logs['exception'] = str(e)

      return self._portage_emerge_stats
