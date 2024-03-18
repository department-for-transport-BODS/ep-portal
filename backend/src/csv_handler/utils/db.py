import json
from os import getenv
from sqlalchemy import MetaData, create_engine, func, select, Table, case, asc, desc
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session
from sys import exit
from typing import List
from .aws import get_secret
from .csv_validator import Registration
from .logger import console, log
from .pydant_model import DBCreds, SearchQuery
from .exceptions import RecordIsAlreadyExist, LimitExceeded, LimitIsNotSet
from .data import common_keys_comparsion
from sqlalchemy.orm import Query
from central_config.env import PROJECT_ENV

class CreateEngine:
    @staticmethod
    def get_db_creds():
        creds = None

        try:
            if PROJECT_ENV != "local":
                secret = get_secret(getenv("POSTGRES_CREDENTIALS"))
                creds = DBCreds(**json.loads(secret["text_secret_data"]))
            else:
                creds = DBCreds(
                    **{
                        "username": getenv("POSTGRES_USER", "postgres"),
                        "password": getenv("POSTGRES_PASSWORD", "postgres"),
                    }
                )
        except Exception as e:
            print(f"The error '{e}' occurred")
            exit(1)
        return creds

    @staticmethod
    def get_engine():
        engine = None
        creds = CreateEngine.get_db_creds()
        try:
            engine = create_engine(
                f"postgresql://{creds.PG_USER}:{creds.PG_PASSWORD}@{creds.PG_HOST}:{creds.PG_PORT}/{creds.PG_DB}"
            )
            connection = engine.connect()
            print("Connection to PostgreSQL DB successful")
            connection.close()
        except Exception as e:
            print(f"The error '{e}' occurred")
            exit(1)
        return engine


def add_or_get_record(column_name: str, value: str, session: Session, Model, record):
    """
    Add a new record to the table if it doesn't exist, or get the id of the existing record.
    """
    try:
        stmt = select(Model).where(getattr(Model, column_name) == value)
        if not session.query(stmt.exists()).scalar():
            new_record = record
            session.add(new_record)
            session.flush()
            log.debug(f"New added record id: {new_record.id}, to table: {Model}")
            session.commit()
            return new_record.id
        else:
            existing_record = (
                session.query(Model)
                .filter(getattr(Model, column_name) == value)
                .first()
            )
            return existing_record.id
    except Exception as e:
        log.error(f"Error: {e}")
        session.rollback()
        return None


class AutoMappingModels:
    def __init__(self):
        self.engine = CreateEngine.get_engine()
        self.Base = automap_base()
        self.Base.prepare(autoload_with=self.engine)
        self.EPRegistration = self.Base.classes.ep_registration
        self.OTCOperator = self.Base.classes.otc_operator
        self.OTCLicence = self.Base.classes.otc_licence
        self.Bods_data_catalogue = self.Base.classes.bods_data_catalogue
        self.OTCLicence.__repr__ = (
            lambda self: f"<OTCLicence(licence_number='{self.licence_number}', licence_status='{self.licence_status}, otc_licence_id={self.otc_licence_id}')>"
        )
        self.OTCOperator.__repr__ = (
            lambda self: f"<OTCOperator(operator_name='{self.operator_name}', operator_id='{self.otc_operator_id}')>"
        )
        self.EPRegistration.__repr__ = (
            lambda self: f"<EPRegistration(route_number='{self.route_number}', route_description='{self.route_description}', variation_number='{self.variation_number}', start_point='{self.start_point}', finish_point='{self.finish_point}', via='{self.via}', subsidised='{self.subsidised}', subsidy_detail='{self.subsidy_detail}', is_short_notice='{self.is_short_notice}', received_date='{self.received_date}', granted_date='{self.granted_date}', effective_date='{self.effective_date}', end_date='{self.end_date}', otc_operator_id='{self.otc_operator_id}', bus_service_type_id='{self.bus_service_type_id}', bus_service_type_description='{self.bus_service_type_description}', registration_number='{self.registration_number}', traffic_area_id='{self.traffic_area_id}', application_type='{self.application_type}', publication_text='{self.publication_text}', other_details='{self.other_details}')>"
        )
        self.Bods_data_catalogue.__repr__ = (
            lambda self: f"<Bods_data_catalogue(id='{self.id}', xml_service_code='{self.xml_service_code}', variation_number='{self.variation_number}', service_type_description='{self.service_type_description}', published_status='{self.published_status}', requires_attention='{self.requires_attention}', timeliness_status='{self.timeliness_status}')>"
        )

    def get_tables(self):
        return {
            "EPRegistration": self.EPRegistration,
            "OTCOperator": self.OTCOperator,
            "OTCLicence": self.OTCLicence,
        }


def add_filter_to_query(query: Query, column, value, strict_mode: bool = False):
    if strict_mode:
        return query.filter(column == value)

    return query.filter(column.like(f"%{value}%"))


class DBManager:
    @classmethod
    def fetch_operator_record(
        cls, operator_name: str, session: Session, OTCOperator, operator_record
    ):
        operator_record_id = add_or_get_record(
            "operator_name", operator_name, session, OTCOperator, operator_record
        )
        return operator_record_id

    @classmethod
    def fetch_licence_record(
        cls, licence_number: str, session: Session, OTCLicence, licence_record
    ):
        licence_record_id = add_or_get_record(
            "licence_number", licence_number, session, OTCLicence, licence_record
        )
        return licence_record_id

    @classmethod
    def upsert_record_to_ep_registration_table(
        cls,
        record: Registration,
        operator_record_id: int,
        licence_record_id: int,
        session: Session,
        EPRegistration: Table,
    ):
        """Add or update the record to the EPRegistration table

        Args:
            record (Registration):
            operator_record_id (int):
            licence_record_id (int):
            session (Session):
            EPRegistration (Table): Target table

        Raises:
            RecordIsAlreadyExist: If the record already exists in the database
        """
        # Add or update the record to the EPRegistration table
        # case 1: Record already exists in the database
        existing_record = (
            session.query(EPRegistration)
            .filter(
                EPRegistration.registration_number == record.registration_number,
                EPRegistration.otc_operator_id == operator_record_id,
                EPRegistration.variation_number == record.variation_number,
            )
            .one_or_none()
        )

        if existing_record:
            record_dict = record.model_dump()
            existing_record_dict = existing_record.__dict__
            if common_keys_comparsion(record_dict, existing_record_dict):
                # case 1.1: Check if all the fields are the same
                # All fields are the same, reject with an error
                # log.debug(
                #     f"Record already exists with the same fields: {existing_record.id}"
                # )
                raise RecordIsAlreadyExist("Record already exists with the same fields")

            else:
                # case 1.2: Not all fields are the same, update the record
                existing_record.route_number = record.route_number
                existing_record.route_description = record.route_description
                existing_record.variation_number = record.variation_number
                existing_record.start_point = record.start_point
                existing_record.finish_point = record.finish_point
                existing_record.via = record.via
                existing_record.subsidised = record.subsidised
                existing_record.subsidy_detail = record.subsidy_detail
                existing_record.is_short_notice = record.is_short_notice
                existing_record.received_date = record.received_date
                existing_record.granted_date = record.granted_date
                existing_record.effective_date = record.effective_date
                existing_record.end_date = record.end_date
                existing_record.bus_service_type_id = record.bus_service_type_id
                existing_record.bus_service_type_description = (
                    record.bus_service_type_description
                )
                existing_record.traffic_area_id = record.traffic_area_id
                existing_record.application_type = record.application_type
                existing_record.publication_text = record.publication_text
                existing_record.other_details = record.other_details
                existing_record.otc_licence_id = licence_record_id
                session.commit()
                log.debug(f"Updated EP registration record: {existing_record.id}")

        else:
            # case 2: Record does not exist, create a new record
            ep_registration_record = EPRegistration(
                route_number=record.route_number,
                route_description=record.route_description,
                variation_number=record.variation_number,
                start_point=record.start_point,
                finish_point=record.finish_point,
                via=record.via,
                subsidised=record.subsidised,
                subsidy_detail=record.subsidy_detail,
                is_short_notice=record.is_short_notice,
                received_date=record.received_date,
                granted_date=record.granted_date,
                effective_date=record.effective_date,
                end_date=record.end_date,
                bus_service_type_id=record.bus_service_type_id,
                bus_service_type_description=record.bus_service_type_description,
                registration_number=record.registration_number,
                traffic_area_id=record.traffic_area_id,
                application_type=record.application_type,
                publication_text=record.publication_text,
                other_details=record.other_details,
                otc_operator_id=operator_record_id,
                otc_licence_id=licence_record_id,
            )
            session.add(ep_registration_record)
            session.commit()
            log.debug(f"New EP registration record: {ep_registration_record.id}")

    @classmethod
    def get_records(
        cls,
        exclude_variations: bool = False,
        registration_number: str = None,
        operator_name: str = None,
        route_number: str = None,
        license_number: str = None,
        limit: int | None = None,
        page: int | None = None,
        strict_mode: bool = False,
    ) -> List[dict]:
        """Get records from the database based on the search query

        Args:
            exclude_variations (bool, optional): Defaults to False.
            registration_number (str, optional): Defaults to None.
            operator_name (str, optional): Defaults to None.
            route_number (str, optional): Defaults to None.
            license_number (str, optional): Defaults to None.
            limit (int | None, optional): Defaults to None.
            page (int | None, optional): Defaults to None.
            strict_mode (bool, optional): Defaults to False.

        Raises:
            LimitIsNotSet: If the limit is not set when the page is provided
            LimitExceeded: If the page number exceeds the total number of records

        Returns:
            [dict]: List of records each as a dictionary
        """
        models = AutoMappingModels()
        session = Session(models.engine)
        EPRegistration = models.EPRegistration
        OTCOperator = models.OTCOperator
        OTCLicence = models.OTCLicence

        records = (
            session.query(
                EPRegistration.variation_number.label("variationNumber"),
                EPRegistration.registration_number.label("registrationNumber"),
                OTCOperator.operator_name.label("operatorName"),
                OTCLicence.licence_number.label("licenceNumber"),
            )
            .join(OTCOperator, EPRegistration.otc_operator_id == OTCOperator.id)
            .join(OTCLicence, EPRegistration.otc_licence_id == OTCLicence.id)
        )

        if exclude_variations:
            latest_ids = (
                select(func.max(EPRegistration.variation_number))
                .group_by(
                    EPRegistration.registration_number,
                    EPRegistration.otc_operator_id,
                )
                .subquery()
            )
            records = records.filter(
                EPRegistration.variation_number.in_(select(latest_ids))
            )

        if license_number:
            records = add_filter_to_query(
                records, OTCLicence.licence_number, license_number, strict_mode
            )

        if registration_number:
            records = add_filter_to_query(
                records,
                EPRegistration.registration_number,
                registration_number,
                strict_mode,
            )

        if operator_name:
            records = add_filter_to_query(
                records, OTCOperator.operator_name, operator_name, strict_mode
            )

        if route_number:
            records = add_filter_to_query(
                records, EPRegistration.route_number, route_number, strict_mode
            )

        if page:
            console.log(records.count())
            cls.record_count = records.count()
            if limit is None:
                raise LimitIsNotSet("Limit must be provided when page is provided")
            offset = (page - 1) * limit
            if offset < records.count():
                records = records.offset(offset)
            else:
                raise LimitExceeded("Page number exceeds the total number of records")

        if limit:
            records = records.limit(limit)

        return [rec._asdict() for rec in records.all()]

    @classmethod
    def construct_next_page_url(
        cls, search_query: SearchQuery, host: str, path: str
    ) -> str:
        """Construct the next page url

        Args:
            search_query (SearchQuery): Search query object from the request
            host (str): Host
            path (str): Path

        Returns:
           NextPage (str) : URL for the next page
        """
        if search_query.page is None:
            return
        if search_query.limit is None:
            return
        if cls.record_count is None:
            return
        # Calculate the next page
        search_query.page += 1
        if search_query.page * search_query.limit > cls.record_count:
            return
        search_params = search_query.model_dump(exclude_none=True, by_alias=True)
        params_str = "&".join([f"{k}={v}" for k, v in search_params.items()])
        return f"{host}{path}?{params_str}"

    @classmethod
    def get_all_records(cls):
        models = AutoMappingModels()
        session = Session(models.engine)
        EPRegistration = models.EPRegistration
        OTCOperator = models.OTCOperator
        OTCLicence = models.OTCLicence
        Bods_data_catalogue = models.Bods_data_catalogue

        records = (
            session.query(
                EPRegistration.registration_number.label("registrationNumber"),
                EPRegistration.route_number.label("routeNumber"),
                EPRegistration.route_description.label("routeDescription"),
                EPRegistration.variation_number.label("variationNumber"),
                EPRegistration.start_point.label("startPoint"),
                EPRegistration.finish_point.label("finishPoint"),
                EPRegistration.via.label("via"),
                EPRegistration.subsidised.label("subsidised"),
                EPRegistration.subsidy_detail.label("subsidyDetail"),
                EPRegistration.is_short_notice.label("isShortNotice"),
                EPRegistration.received_date.label("receivedDate"),
                EPRegistration.granted_date.label("grantedDate"),
                EPRegistration.effective_date.label("effectiveDate"),
                EPRegistration.end_date.label("endDate"),
                EPRegistration.bus_service_type_id.label("busServiceTypeId"),
                EPRegistration.bus_service_type_description.label(
                    "busServiceTypeDescription"
                ),
                EPRegistration.traffic_area_id.label("trafficAreaId"),
                EPRegistration.application_type.label("applicationType"),
                EPRegistration.publication_text.label("publicationText"),
                OTCOperator.operator_name.label("operatorName"),
                OTCLicence.licence_number.label("licenceNumber"),
                OTCLicence.licence_status.label("licenceStatus"),
                Bods_data_catalogue.requires_attention,
                Bods_data_catalogue.timeliness_status

            )
            .filter(EPRegistration.otc_operator_id == OTCOperator.id)
            .filter(EPRegistration.otc_licence_id == OTCLicence.id)
            .filter(EPRegistration.registration_number == Bods_data_catalogue.xml_service_code)
            
        )

        return [rec._asdict() for rec in records.all()]

    @classmethod
    def get_record_reuiqred_attention_percentage(cls):
        models = AutoMappingModels()
        session = Session(models.engine)
        EPRegistration = models.EPRegistration
        OTCOperator = models.OTCOperator
        OTCLicence = models.OTCLicence
        Bods_data_catalogue = models.Bods_data_catalogue
        subquery_q2 = (
            session.query(
                func.count(EPRegistration.registration_number).label("count"),
                OTCLicence.licence_number,
                Bods_data_catalogue.requires_attention,
                OTCOperator.operator_name,
                OTCLicence.licence_status
            )
            .join(OTCLicence, OTCLicence.id == EPRegistration.otc_licence_id)
            .join(
                Bods_data_catalogue,
                EPRegistration.registration_number
                == Bods_data_catalogue.xml_service_code,
            )
            .join(OTCOperator, OTCOperator.id == EPRegistration.otc_operator_id)
            .group_by(
                OTCLicence.licence_number,
                OTCOperator.operator_name,
                Bods_data_catalogue.requires_attention,
                OTCLicence.licence_status
            )
            .subquery()
        )

        query = (
            session.query(
                subquery_q2.c.licence_number,
                subquery_q2.c.operator_name,
                subquery_q2.c.licence_status,
                func.round(
                    (
                        100.0
                        * func.sum(
                            case(
                                (
                                    (
                                        subquery_q2.c.requires_attention,
                                        subquery_q2.c.count,
                                    )
                                ),
                                else_=0,
                            )
                        )
                        / func.sum(subquery_q2.c.count)
                    ),
                    2,
                ).label("requires_attention"),
                func.sum(subquery_q2.c.count).label("total_services"),
            )
            .group_by(subquery_q2.c.licence_number, subquery_q2.c.operator_name, subquery_q2.c.licence_status)
            .order_by(desc("total_services"))
        )


        return [rec._asdict() for rec in query.all()]


def send_to_db(records: List[Registration]):
    # validated_records: List[Registration] = MockData.mock_user_csv_record()
    models = AutoMappingModels()
    engine = models.engine
    tables = models.get_tables()
    OTCOperator = tables["OTCOperator"]
    OTCLicence = tables["OTCLicence"]
    EPRegistration = tables["EPRegistration"]
    # Check if the licence number exists in the OTC database
    # validated_records = validate_licence_number_existence(validated_records)
    db_invalid_insertion = []
    for idx, record_and_licence in records["valid_records"].items():
        try:
            # Create a new session
            session = Session(engine)
            # Prepare operator object and added to the database
            record, licence = record_and_licence
            OTCOperator_record = OTCOperator(
                operator_name=licence.operator_details.operator_name,
                otc_operator_id=licence.operator_details.otc_operator_id,
            )

            # Add or fetch the operator id from the database
            operator_record_id = DBManager.fetch_operator_record(
                licence.operator_details.operator_name,
                session,
                OTCOperator,
                OTCOperator_record,
            )

            # Prepare licence object and added to the database
            OTCLicence_record = OTCLicence(
                licence_number=licence.licence_details.licence_number,
                licence_status=licence.licence_details.licence_status,
                otc_licence_id=licence.licence_details.otc_licence_id,
            )

            # Add or fetch the licence id from the database
            licence_record_id = DBManager.fetch_licence_record(
                licence.licence_details.licence_number,
                session,
                OTCLicence,
                OTCLicence_record,
            )
            # log.debug(f"Record with number: {idx} going to db")
            # Add the record to the EPRegistration table
            DBManager.upsert_record_to_ep_registration_table(
                record, operator_record_id, licence_record_id, session, EPRegistration
            )
        except RecordIsAlreadyExist:
            records["invalid_records"].update(
                {
                    idx: [
                        {"Dublicated Record": "Record is already exist in the database"}
                    ]
                }
            )
            db_invalid_insertion.append(idx)
        except Exception:
            console.print_exception(show_locals=False)
            session.rollback()
        finally:
            session.close()
    # Remove records from the valid_records dictionary that were not added to the database
    for idx in db_invalid_insertion:
        del records["valid_records"][f"{idx}"]

    return records
