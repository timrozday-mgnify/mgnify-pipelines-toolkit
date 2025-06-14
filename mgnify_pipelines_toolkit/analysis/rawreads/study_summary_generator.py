#!/usr/bin/env python
# -*- coding: utf-8 -*-
import shutil
from shutil import SameFileError

# Copyright 2024-2025 EMBL - European Bioinformatics Institute
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import click
from collections import defaultdict
import glob
import logging
from pathlib import Path
from typing import Union, List

import pandas as pd

from mgnify_pipelines_toolkit.constants.db_labels import (
    RRAP_TAXDB_LABELS,
    RRAP_FUNCDB_LABELS,
)
from mgnify_pipelines_toolkit.constants.tax_ranks import (
    _SILVA_TAX_RANKS,
    _MOTUS_TAX_RANKS,
)
from mgnify_pipelines_toolkit.schemas.schemas import (
    RawReadsPassedRunsSchema,
    RawReadsNonINSDCPassedRunsSchema,
    TaxonSchema,
    MotusTaxonSchema,
    FunctionProfileSchema,
    validate_dataframe,
)

logging.basicConfig(level=logging.DEBUG)


@click.group()
def cli():
    pass


def get_file(
    run_acc: str, analyses_dir: Path, db_label: str
) -> Union[Path, List[Path]]:
    """Takes path information for a particular analysis and db_label combo, and returns any existing files.

    :param run_acc: Run accession for the tax file that should be retrieved.
    :type run_acc: str
    :param analyses_dir: The path to the directory containing all of the analyses,
            including the tax file corresponding to :param:`run_acc`.
    :type analyses_dir: Path
    :param db_label: One of the database labels that results might exist for,
            values of which come from the imported constants ``RRAP_TAXDB_LABELS`` and ``RRAP_FUNCDB_LABELS``.
    :type db_label: str
    :return: A :class:`Path` object if :param:`db_label` comes from ``RRAP_TAXDB_LABELS`` or ``RRAP_FUNCDB_LABELS``.
    :rtype: Union[Path, List[Path]]
    """

    analysis_file = None

    if db_label in RRAP_TAXDB_LABELS + RRAP_FUNCDB_LABELS:

        if db_label in RRAP_TAXDB_LABELS:
            db_dir = 'taxonomy-summary'
        else:
            db_dir = 'function-summary'
        db_path = Path(f"{analyses_dir}/{run_acc}/{db_dir}/{db_label}")

        if not db_path.exists():
            logging.debug(
                f"DB {db_path} doesn't exist for {run_acc}. Skipping"
            )  # or error?
            return

        analysis_file = Path(
            f"{analyses_dir}/{run_acc}/{db_dir}/{db_label}/{run_acc}_{db_label}.txt"
        )
        if not analysis_file.exists():
            logging.error(
                f"DB path exists but file doesn't - exiting. Path: {analysis_file}"
            )
            exit(1)

        file_size = analysis_file.stat().st_size
        if (
            file_size == 0
        ):  # Pipeline can generate files that are empty for ITS DBs (UNITE and ITSoneDB),
            # so need to skip those. Should probably fix that at some point
            logging.debug(
                f"File {analysis_file} exists but is empty, so will be skipping it."
            )
            analysis_file = None

    return analysis_file


def parse_one_file(
    run_acc: str, tax_file: Path
) -> pd.DataFrame:
    return


def parse_one_tax_file(
    run_acc: str, tax_file: Path, db_label: str
) -> pd.DataFrame:
    """Parses a taxonomy file, and returns it as a pandas DataFrame object.

    :param run_acc: Run accession of the taxonomy file that will be parsed.
    :type run_acc: str
    :param tax_file: Taxonomy file that will be parsed.
    :type tax_file: Path
    :param db_label: One of the database labels that results might exist for,
        values of which come from the imported constants ``RRAP_TAXDB_LABELS` and `RRAP_FUNCDB_LABELS``.
    :type db_label: str
    :return: The parsed :param:`tax_file` as a :class:`pd.DataFrame` object
    :rtype: pd.DataFrame
    """

    tax_ranks = _MOTUS_TAX_RANKS if db_label == 'mOTUs' else _SILVA_TAX_RANKS
    res_df = pd.read_csv(tax_file, sep="\t", names=["Count"] + tax_ranks)
    res_df = res_df.fillna("")

    validate_dataframe(res_df, MotusTaxonSchema if db_label == 'mOTUs' else TaxonSchema, str(tax_file))

    res_df["full_taxon"] = res_df.iloc[:, 1:].apply(
        lambda x: ";".join(x).strip(";"), axis=1
    )
    final_df = res_df.iloc[:, [0, -1]]
    final_df = final_df.set_index("full_taxon")
    final_df.columns = [run_acc]

    return final_df


def parse_one_func_file(
        run_acc: str, func_file: Path, db_label: str
) -> pd.DataFrame:
    """Parses a functional profile file, and returns it as a pandas DataFrame object.

    :param run_acc: Run accession of the taxonomy file that will be parsed.
    :type run_acc: str
    :param func_file: Functional profile file that will be parsed.
    :type func_file: Path
    :param db_label: One of the database labels that results might exist for,
        values of which come from the imported constants ``RRAP_TAXDB_LABELS` and `RRAP_FUNCDB_LABELS``.
    :type db_label: str
    :return: The parsed :param:`func_file` as a :class:`pd.DataFrame` object
    :rtype: pd.DataFrame
    """

    res_df = pd.read_csv(
        func_file, sep="\t",
        names=["Function accession", "Count", "Coverage Depth",
               "Coverage Breadth"],
        skiprows=1,
        dtype={
            "Count": int,
            "Coverage Depth": float,
            "Coverage Breadth": float
        }
    ).set_index('Function accession')
    res_df = res_df.fillna(0)

    validate_dataframe(res_df, FunctionProfileSchema, str(func_file))

    final_df = res_df[['Count']]
    final_df.columns = [run_acc]

    return final_df


def generate_db_summary(
    db_label: str, analysis_dfs: dict[Path], output_prefix: str
) -> None:
    """Takes paired run accessions taxonomy dataframes in the form of a dictionary,
    and respective db_label, joins them together, and generates a study-wide summary
    in the form of a .tsv file.

    :param db_label: One of the database labels that results might exist for,
            values of which come from the imported constants ``RRAP_TAXDB_LABELS` and `RRAP_FUNCDB_LABELS``.
    :param tax_dfs: Dictionary where the key is a run accession,
        and values are one parsed taxonomy dataframe if the :param:db_label comes from ``RRAP_TAXDB_LABELS` or `RRAP_FUNCDB_LABELS``.
        These dataframes are parsed by :func:`parse_one_tax_file` or `parse_one_func_file`.
    :type tax_dfs: defaultdict[Path]
    :param output_prefix: Prefix to be added to the generated summary file.
    :type output_prefix: str
    """

    if db_label in RRAP_TAXDB_LABELS + RRAP_FUNCDB_LABELS:
        df_list = []

        for run_acc, analysis_df in analysis_dfs.items():
            parse_file_f = parse_one_tax_file if db_label in RRAP_TAXDB_LABELS else parse_one_func_file
            res_df = parse_file_f(run_acc, analysis_df, db_label)
            df_list.append(res_df)

        res_df = pd.concat(df_list, axis=1).fillna(0)
        res_df = res_df.sort_index()
        res_df = res_df.astype(int)

        res_df.to_csv(
            f"{output_prefix}_{db_label}_study_summary.tsv",
            sep="\t",
            index_label="taxonomy" if db_label in RRAP_TAXDB_LABELS else "function",
        )


def organise_study_summaries(all_study_summaries: List[str]) -> defaultdict[List]:
    """Matches different summary files of the same database label and analysis
    type into a dictionary to help merge
    the correct summaries.

    :param all_study_summaries: List of file paths to different summary files
    :type all_study_summaries: List[str]
    :return: Organised dictionary where each summary is paired to a specific
        database label key to be merged together.
    :rtype: defaultdict[List]
    """
    summaries_dict = defaultdict(list)

    for summary in all_study_summaries:
        summary_path = Path(summary)
        summary_filename = summary_path.stem

        summary_db_label = summary_filename.split("_")[1]

        summaries_dict[summary_db_label].append(summary_path)

    return summaries_dict


@cli.command(
    "summarise",
    options_metavar="-r <runs> -a <analyses_dir> -p <output_prefix>",
    short_help="Generate study-level summaries of raw-read analysis results.",
)
@click.option(
    "-r",
    "--runs",
    required=True,
    help="CSV file containing successful analyses generated by the pipeline",
    type=click.Path(exists=True, path_type=Path, dir_okay=False),
)
@click.option(
    "-a",
    "--analyses_dir",
    required=True,
    help="Input directory to where all the individual analyses subdirectories for summarising",
    type=click.Path(exists=True, path_type=Path, file_okay=False),
)
@click.option(
    "-p", "--output_prefix", required=True, help="Prefix to summary files", type=str
)
@click.option(
    "--non_insdc",
    default=False,
    is_flag=True,
    help="If run accessions aren't INSDC-formatted",
)
def summarise_analyses(
    runs: Path, analyses_dir: Path, output_prefix: str, non_insdc: bool
) -> None:
    """Function that will take a file of pipeline-successful run accessions
    that should be used for the generation of the relevant db-specific
    study-level summary files.
    \f

    :param runs: Path to a qc_passed_runs file from the pipeline execution.
        Contains the accessions of runs that should therefore be included in the generated
        summaries.
    :type runs: Path
    :param analyses_dir: The path to the directory containing all of the analyses.
    :type analyses_dir: Path
    :param output_prefix: Prefix to be added to the generated summary file.
    :type output_prefix: str
    """
    runs_df = pd.read_csv(runs, names=["run", "status", "reads",
                                       "qc", "decontam", "motus",
                                       "silva_ssu", "silva_lsu", "pfam"])

    if not non_insdc:
        RawReadsPassedRunsSchema(
            runs_df
        )  # Run validation on the successful_runs .csv file
    else:
        RawReadsNonINSDCPassedRunsSchema(runs_df)

    all_db_labels = RRAP_TAXDB_LABELS + RRAP_FUNCDB_LABELS
    for db_label in all_db_labels:

        analysis_files = {}
        for run_acc in runs_df['run']:
            analysis_file = get_file(run_acc, analyses_dir, db_label)

            if analysis_file:
                analysis_files[run_acc] = analysis_file

        if analysis_files:
            generate_db_summary(db_label, analysis_files, output_prefix)


@cli.command(
    "merge",
    options_metavar="-a <analyses_dir> -p <output_prefix>",
    short_help="Merge multiple study-level summaries of raw-read analysis.",
)
@click.option(
    "-a",
    "--analyses_dir",
    required=True,
    help="Input directory to where all the individual analyses subdirectories for merging",
    type=click.Path(exists=True, file_okay=False),
)
@click.option(
    "-p",
    "--output_prefix",
    required=True,
    help="Prefix to merged summary files",
    type=str,
)
def merge_summaries(analyses_dir: str, output_prefix: str) -> None:
    """Function that will take a file path containing study-level
    summaries that should be merged together on a per-db
    basis.
    \f

    :param analyses_dir: The filepath to the directory containing all of the analyses.
    :type analyses_dir: str
    :param output_prefix: Prefix to be added to the generated summary file.
    :type output_prefix: str
    """

    all_study_summaries = glob.glob(f"{analyses_dir}/*_study_summary.tsv")

    summaries_dict = organise_study_summaries(all_study_summaries)

    for db_label, summaries in summaries_dict.items():
        merged_summary_name = f"{output_prefix}_{db_label}_study_summary.tsv"
        if len(summaries) > 1:
            res_df = pd.read_csv(summaries[0], sep="\t", index_col=0)
            for summary in summaries[1:]:
                curr_df = pd.read_csv(summary, sep="\t", index_col=0)
                res_df = res_df.join(curr_df, how="outer")
                res_df = res_df.fillna(0)
                res_df = res_df.astype(int)

            res_df = res_df.reindex(sorted(res_df.columns), axis=1)
            res_df.to_csv(
                merged_summary_name,
                sep="\t",
                index_label="taxonomy" if db_label in RRAP_TAXDB_LABELS else "function",
            )
        elif len(summaries) == 1:
            logging.info(
                f"Only one summary ({summaries[0]}) so will use that as {merged_summary_name}"
            )
            try:
                shutil.copyfile(summaries[0], merged_summary_name)
            except SameFileError:
                pass


if __name__ == "__main__":
    cli()
