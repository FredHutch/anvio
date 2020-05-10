# -*- coding: utf-8
# pylint: disable=line-too-long
"""A library to help anvi'o desribe itself"""

import os
import sys
import glob
import json
import importlib

from collections import Counter

import anvio
import anvio.utils as utils
import anvio.terminal as terminal
import anvio.filesnpaths as filesnpaths

from anvio.errors import ConfigError
from anvio.docs import ANVIO_ARTIFACTS
from anvio.summaryhtml import SummaryHTMLOutput


__author__ = "Developers of anvi'o (see AUTHORS.txt)"
__copyright__ = "Copyleft 2015-2018, the Meren Lab (http://merenlab.org/)"
__credits__ = []
__license__ = "GPL 3.0"
__version__ = anvio.__version__
__maintainer__ = "A. Murat Eren"
__email__ = "a.murat.eren@gmail.com"
__status__ = "Development"


G = lambda d: [p for p in glob.glob(os.path.join(d, 'anvi-*')) if utils.is_program_exists(p, dont_raise=True)]
M = lambda m: [x for x in G(os.path.dirname(utils.is_program_exists(m)))]
S = lambda s: [x for x in G(os.path.dirname(utils.is_program_exists(s)))]
J = lambda x: '\n'.join(x) if x else ''


run = terminal.Run()
progress = terminal.Progress()


def get_until_blank(output):
    section = []
    while 1:
        if output[0] == '':
            break
        else:
            section.append(output.pop(0))

    return section


def get_meta_information_from_file(file_path, meta_tag):
    all_lines = [l.strip() for l in open(file_path, 'rU').readlines()]

    meta_tag_content = ''

    while 1:
        if not len(all_lines):
            return []

        if not all_lines[0].startswith(meta_tag):
            all_lines.pop(0)
        else:
            break

    meta_tag_content = all_lines.pop(0)

    while 1:
        line = all_lines.pop(0)
        if line == '' or line.startswith('__'):
            break
        else:
            meta_tag_content += line

    if meta_tag_content:
        return eval(meta_tag_content.split('=')[1].strip())
    else:
        return []


def get_param_set(output):
    if output[0] in ['optional arguments:', 'positional arguments:']:
        section = output.pop(0)
        desc = ''
        _params = J([p for p in get_until_blank(output) if not p.startswith('  -h, --help')])
    else:
        section = output.pop(0)
        if output[0].startswith('  -'):
            # no description, goes into params immediately (someone did a crappy job)
            desc = ''
        else:
            desc = get_until_blank(output)
            output.pop(0)

        _params = J(get_until_blank(output))

    return section, desc, _params


def skip_until_usage(output):
    while 1:
        if not len(output):
            return

        if output[0].startswith('usage:'):
            return

        output.pop(0)


def parse_help_output(output):
    skip_until_usage(output)

    if not len(output):
        raise ConfigError("This is not the help menu output we are looking for.")

    if not output[0].startswith('usage:'):
        raise ConfigError("This output does not seem to have the proper usage statement.")

    usage = J([l[7:] for l in get_until_blank(output)])

    if output.pop(0) != '':
        raise ConfigError("This output is missing the description start marker.")

    description = J(get_until_blank(output))

    params = {}
    while 1:
        if output.pop(0) != '':
            raise ConfigError("The params section does not seem to be where this script expects to find it.")

        if not len(output):
            break

        section, desc, _params = get_param_set(output)
        if _params == '':
            pass
        else:
            params[section] = {'description': J(desc),
                               'params': _params}

    return usage, description, params, output


class AnvioPrograms:
    def __init__(self, args, r=terminal.Run(), p=terminal.Progress()):
        self.args = args
        self.run = r
        self.progress = p

        A = lambda x: args.__dict__[x] if x in args.__dict__ else None
        self.program_names_to_focus = A("program_names_to_focus")

        try:
            self.main_program_filepaths = M('anvi-interactive')
            self.script_filepaths = S('anvi-script-gen-programs-vignette')

            self.all_program_filepaths = sorted(list(set(self.main_program_filepaths + self.script_filepaths)))
        except:
            raise ConfigError("Something is wrong. Either your installation or anvi'o setup on this computer is missing some of "
                              "the fundamental programs, or your configuration is broken :/")

        if not len(self.main_program_filepaths) or not len(self.script_filepaths):
            raise ConfigError("Somethings fishy is happening. This script is unable to find things that want to be found :(")

        self.run.info("Main anvi'o programs found", len(self.main_program_filepaths))
        self.run.info("Anvi'o ad hoc scripts found", len(self.script_filepaths))

        if self.program_names_to_focus:
            self.program_names_to_focus = [p.strip() for p in self.program_names_to_focus.split(',')]
            run.info("Program names to focus", len(self.program_names_to_focus))

            self.all_program_filepaths = [p for p in self.all_program_filepaths if os.path.basename(p) in self.program_names_to_focus]

            if not len(self.all_program_filepaths):
                raise ConfigError("No anvi'o programs left to analyze after changing the focus to your list of program names. "
                                  "Probably there is a typo or something :/")


    def init_programs(self, okay_if_no_meta=False, quiet=False):
        """Initializes the `self.programs` dictionary."""

        num_all_programs = len(self.all_program_filepaths)

        meta_count = 0
        self.programs = {}
        self.progress.new('Characterizing program', progress_total_items=num_all_programs)

        for program_filepath in self.all_program_filepaths:
            self.progress.update(os.path.basename(program_filepath), increment=True)

            program = Program(program_filepath, r=self.run, p=self.progress)

            if program.meta_info['provides']['value'] or program.meta_info['requires']['value']:
                meta_count += 1

            if not (program.meta_info['provides']['value'] or program.meta_info['requires']['value']) and not okay_if_no_meta:
                pass
            else:
                self.programs[program.name] = program

        self.progress.end()

        if not meta_count and not okay_if_no_meta:
            raise ConfigError("None of the %d anvi'o programs found contained any provides or "
                              "requires statements :/" % len(self.all_program_filepaths))

        if not quiet:
            self.run.info_single("Of %d programs found, %d did contain provides and/or requires "
                                 "statements." % (len(self.all_program_filepaths), meta_count),
                                  nl_after=1, nl_before=1)
        if anvio.DEBUG:
            absentees = ', '.join(list(set([os.path.basename(p) for p in self.all_program_filepaths]) - set(list(self.programs.keys()))))
            self.run.info_single("Here is a list of programs that do not contain any information "
                                 "about themselves: %s" % (absentees), nl_after=1, nl_before=1, mc="red")


class Program:
    def __init__(self, program_path, r=terminal.Run(), p=terminal.Progress()):
        self.run = r
        self.progress = p

        self.program_path = program_path
        self.name = os.path.basename(program_path)

        self.meta_info = {
            'requires': {
                'object_name': '__requires__',
                'null_object': []
            },
            'provides': {
                'object_name': '__provides__',
                'null_object': []
            },
            'tags': {
                'object_name': '__tags__',
                'null_object': []
            },
            'resources': {
                'object_name': '__resources__',
                'null_object': []
            },
            'description': {
                'object_name': '__description__',
                'null_object': ''
            },
            'usage': {
                'object_name': '__usage__',
                'null_object': '',
                'read_as_is': True,
            },
        }

        self.module = self.load_as_module(self.program_path)
        self.get_meta_info()


    def get_meta_info(self):
        for info_type in self.meta_info.keys():
            try:
                info = getattr(self.module, self.meta_info[info_type]['object_name'])
            except AttributeError:
                info = self.meta_info[info_type]['null_object']

            if info_type == 'requires' or info_type == 'provides':
                # these info_types have their items cast as Artifact types
                info = [Artifact(artifact_name) for artifact_name in info]

            if type(info) == str:
                if 'read_as_is' in self.meta_info[info_type] and self.meta_info[info_type]['read_as_is']:
                    info = info
                else:
                    info = info.replace('\n', ' ')

            self.meta_info[info_type]['value'] = info


    def load_as_module(self, path):
        """
        Importing the program as a module has the advantage of grabbing the meta info as python
        objects directly instead of parsing the file lines as a string object. if is not a Python
        file, self.module is None.

        Taken from stackoverflow user Ciro Santilli:
        https://stackoverflow.com/questions/2601047/import-a-python-module-without-the-py-extension/56090741#56090741
        """
        try:
            module_name = os.path.basename(path).replace('-', '_')
            spec = importlib.util.spec_from_loader(
                module_name,
                importlib.machinery.SourceFileLoader(module_name, path)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            sys.modules[module_name] = module
            return module
        except:
            return None


    def __str__(self):
        self.run.warning(None, header='%s' % self.name, lc='green')
        for info_type in self.meta_info:
            self.run.info(info_type, self.meta_info[info_type]['value'])

        return ''


    def __repr__(self):
        return "PROG::%s" % self.name


class Artifact:
    """A class to describe an anvi'o artifact"""

    def __init__(self, artifact_id, internal=True, optional=True, single=True):
        if artifact_id not in ANVIO_ARTIFACTS:
            raise ConfigError("Ehem. Anvi'o does not know about artifact '%s'. There are two was this could happen: "
                              "one, you made a type (easy to fix), two, you just added a new program into anvi'o "
                              "but have not yet updated `anvio/programs.py`." % artifact_id)

        artifact = ANVIO_ARTIFACTS[artifact_id]
        self.id = artifact_id
        self.name = artifact['name']
        self.type = artifact['type']
        self.internal = artifact['internal']

        # attributes set by the context master
        self.single = single
        self.optional = optional


    def __repr__(self):
        return "ARTIFACT::%s" % self.id


class AnvioDocs(AnvioPrograms):
    """Generate a docs output.

       The purpose of this class is to generate a static HTML output with
       interlinked files that serve as the primary documentation for anvi'o
       programs, input files they expect, and output files the generate.

       The default client of this class is `anvi-script-gen-help-docs`.
    """

    def __init__(self, args, r=terminal.Run(), p=terminal.Progress()):
        self.args = args
        self.run = r
        self.progress = p

        A = lambda x: args.__dict__[x] if x in args.__dict__ else None
        self.output_directory_path = A("output_dir") or 'ANVIO-HELP'

        filesnpaths.gen_output_directory(self.output_directory_path, delete_if_exists=True, dont_warn=True)

        AnvioPrograms.__init__(self, args, r=self.run, p=self.progress)


class ProgramsNetwork(AnvioPrograms):
    def __init__(self, args, r=terminal.Run(), p=terminal.Progress()):
        self.args = args
        self.run = r
        self.progress = p

        A = lambda x: args.__dict__[x] if x in args.__dict__ else None
        self.output_file_path = A("output_file") or 'NETWORK.json'

        filesnpaths.is_output_file_writable(self.output_file_path)

        AnvioPrograms.__init__(self, args, r=self.run, p=self.progress)


    def generate(self):
        self.init_programs()
        self.report_network()


    def report_network(self):
        artifact_names_seen = set([])
        artifacts_seen = Counter({})
        all_artifacts = []
        for program in self.programs.values():
            for artifact in program.meta_info['provides']['value'] + program.meta_info['requires']['value']:
                artifacts_seen[artifact.id] += 1
                if not artifact.id in artifact_names_seen:
                    all_artifacts.append(artifact)
                    artifact_names_seen.add(artifact.id)

        programs_seen = Counter({})
        for artifact in all_artifacts:
            for program in self.programs.values():
                for program_artifact in program.meta_info['provides']['value'] + program.meta_info['requires']['value']:
                    if artifact.name == program_artifact.name:
                        programs_seen[program.name] += 1

        network_dict = {"graph": [], "nodes": [], "links": [], "directed": False, "multigraph": False}

        node_indices = {}

        index = 0
        types_seen = set(["PROGRAM"])
        for artifact in all_artifacts:
            types_seen.add(artifact.type)
            network_dict["nodes"].append({"size": artifacts_seen[artifact.id],
                                          "score": 0.5 if artifact.internal else 1,
                                          "color": '#00AA00' if artifact.internal else "#AA0000",
                                          "id": artifact.id,
                                          "name": artifact.name,
                                          "internal": True if artifact.internal else False,
                                          "type": artifact.type})
            node_indices[artifact.id] = index
            index += 1

        for program in self.programs.values():
            network_dict["nodes"].append({"size": programs_seen[program.name],
                                          "score": 0.1,
                                          "color": "#AAAA00",
                                          "id": program.name,
                                          "name": program.name,
                                          "type": "PROGRAM"})
            node_indices[program.name] = index
            index += 1

        for artifact in all_artifacts:
            for program in self.programs.values():
                for artifact_provided in program.meta_info['provides']['value']:
                    if artifact_provided.id == artifact.id:
                        network_dict["links"].append({"source": node_indices[program.name], "target": node_indices[artifact.id]})
                for artifact_needed in program.meta_info['requires']['value']:
                    if artifact_needed.id == artifact.id:
                        network_dict["links"].append({"target": node_indices[program.name], "source": node_indices[artifact.id]})

        open(self.output_file_path, 'w').write(json.dumps(network_dict, indent=2))

        self.run.info('JSON description of network', self.output_file_path)
        self.run.info('Artifacts seen', ', '.join(sorted(list(types_seen))))


class ProgramsVignette(AnvioPrograms):
    def __init__(self, args, r=terminal.Run(), p=terminal.Progress()):
        self.args = args
        self.run = r
        self.progress = p

        self.programs_to_skip = ['anvi-script-gen-programs-vignette']

        AnvioPrograms.__init__(self, args, r=self.run, p=self.progress)

        A = lambda x: args.__dict__[x] if x in args.__dict__ else None
        self.output_file_path = A("output_file")


    def generate(self):
        self.init_programs(okay_if_no_meta = True, quiet = True)

        d = {}
        log_file = filesnpaths.get_temp_file_path()
        for i, program_name in enumerate(self.programs):
            program = self.programs[program_name]

            if program_name in self.programs_to_skip:
                run.warning("Someone doesn't want %s to be in the output :/ Fine. Skipping." % (program.name))

            progress.new('Bleep bloop')
            progress.update('%s (%d of %d)' % (program_name, i+1, len(self.programs)))

            output = utils.run_command_STDIN('%s --help --quiet' % (program.program_path), log_file, '').split('\n')

            if anvio.DEBUG:
                    usage, description, params, output = parse_help_output(output)
            else:
                try:
                    usage, description, params, output = parse_help_output(output)
                except Exception as e:
                    progress.end()
                    run.warning("The program '%s' does not seem to have the expected help menu output. Skipping to the next. "
                                "For the curious, this was the error message: '%s'" % (program.name, str(e).strip()))
                    continue

            d[program.name] = {'usage': usage,
                               'description': description,
                               'params': params,
                               'tags': program.meta_info['tags']['value'],
                               'resources': program.meta_info['resources']['value']}

            progress.end()

        os.remove(log_file)

        # generate output
        program_names = sorted([p for p in d if not p.startswith('anvi-script-')])
        script_names = sorted([p for p in d if p.startswith('anvi-script-')])
        vignette = {'vignette': d,
                    'program_names': program_names,
                    'script_names': script_names,
                    'all_names': program_names + script_names,
                    'meta': {'summary_type': 'vignette',
                             'version': '\n'.join(['|%s|%s|' % (t[0], t[1]) for t in anvio.get_version_tuples()]),
                             'date': utils.get_date()}}

        if anvio.DEBUG:
            run.warning(None, 'THE OUTPUT DICT')
            import json
            print(json.dumps(d, indent=2))

        open(self.output_file_path, 'w').write(SummaryHTMLOutput(vignette, r=run, p=progress).render())

        run.info('Output file', os.path.abspath(self.output_file_path))
