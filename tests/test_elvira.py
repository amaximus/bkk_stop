import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.bkk_stop.elvira import (
    ELVIRA_HEADERS,
    ELVIRA_URL,
    _fetch_station,
    parse_elvira_services,
    rows_from_stationinfo,
    station_code_digits,
)


class ElviraServiceParsingTests(unittest.TestCase):
    def test_booking_required_codes_and_descriptions(self):
        self.assertTrue(
            parse_elvira_services({"services": [{"code": "3880"}]})["booking"]
        )
        self.assertTrue(
            parse_elvira_services(
                {"services": [{"key": "SZOLGALTATAS#3880"}]}
            )["booking"]
        )
        self.assertTrue(
            parse_elvira_services(
                {"services": [{"description": "Helyjegy váltása kötelező"}]}
            )["booking"]
        )
        self.assertFalse(
            parse_elvira_services({"services": [{"code": "#94345"}]})["booking"]
        )
        self.assertFalse(
            parse_elvira_services({"services": [{"code": "13880"}]})["booking"]
        )

    def test_station_code_keeps_nine_trailing_digits(self):
        self.assertEqual(station_code_digits("HU 0080 01000"), "008001000")

    def test_departure_keeps_booking_and_track_without_destination_match(self):
        tz = timezone.utc
        now = datetime(2026, 10, 15, 10, 0, tzinfo=tz)
        start = now + timedelta(minutes=30)
        row = {
            "trainId": "train-1",
            "code": "950",
            "name": "GÖCSEJ",
            "start": start.isoformat(),
            "actualOrEstimatedStart": start.isoformat(),
            "startTrack": "7",
            "services": [{"description": "Helyjegy váltása kötelező"}],
        }

        [departure] = rows_from_stationinfo(
            [row], [], tz, now, now + timedelta(hours=3), "Budapest-Keleti"
        )

        self.assertEqual(departure["trainNumber"], "950")
        self.assertEqual(departure["platform"], "7")
        self.assertTrue(departure["booking"])
        self.assertFalse(departure["destHit"])
        self.assertIsNone(departure["travel"])
        self.assertEqual(
            set(departure),
            {
                "tripId",
                "label",
                "head",
                "dep",
                "sched",
                "platform",
                "vehicle",
                "rawType",
                "trainNumber",
                "travel",
                "destHit",
                "booking",
                "bikesAllowed",
                "wheelchair",
                "color",
                "text",
                "delay",
            },
        )

    def test_destination_match_adds_travel_time(self):
        tz = timezone.utc
        now = datetime(2026, 10, 15, 10, 0, tzinfo=tz)
        start = now + timedelta(minutes=30)
        origin = {
            "trainId": "train-1",
            "code": "950",
            "start": start.isoformat(),
            "actualOrEstimatedStart": start.isoformat(),
        }
        destination = {
            "trainId": "train-1",
            "actualOrEstimatedArrive": (start + timedelta(minutes=62)).isoformat(),
        }

        [departure] = rows_from_stationinfo(
            [origin], [destination], tz, now, now + timedelta(hours=3)
        )

        self.assertTrue(departure["destHit"])
        self.assertEqual(departure["travel"], 62)

    def test_stale_destination_match_does_not_drop_future_origin(self):
        tz = timezone.utc
        now = datetime(2026, 10, 15, 10, 0, tzinfo=tz)
        start = now + timedelta(minutes=30)
        origin = {
            "trainId": "train-1",
            "code": "950",
            "start": start.isoformat(),
            "actualOrEstimatedStart": start.isoformat(),
            "startTrack": "5",
            "services": [{"code": "3880"}],
        }
        destination = {
            "code": "950",
            "actualOrEstimatedArrive": (now - timedelta(minutes=1)).isoformat(),
        }

        [departure] = rows_from_stationinfo(
            [origin], [destination], tz, now, now + timedelta(hours=3)
        )

        self.assertFalse(departure["destHit"])
        self.assertTrue(departure["booking"])
        self.assertEqual(departure["platform"], "5")


class ElviraFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_stationinfo_request_uses_local_midnight_and_500_rows(self):
        response = MagicMock()
        response.status = 200
        response.json = AsyncMock(
            return_value={
                "stationSchedulerDetails": {
                    "departureScheduler": [{"code": "950"}],
                    "arrivalScheduler": [{"code": "950"}],
                }
            }
        )

        class ResponseContext:
            async def __aenter__(self):
                return response

            async def __aexit__(self, *args):
                return None

        session = MagicMock()
        session.post.return_value = ResponseContext()
        tz = timezone.utc

        departures, arrivals = await _fetch_station(session, "008001000", tz)

        self.assertEqual(departures, [{"code": "950"}])
        self.assertEqual(arrivals, [{"code": "950"}])
        args, kwargs = session.post.call_args
        self.assertEqual(args, (ELVIRA_URL,))
        self.assertEqual(kwargs["json"]["type"], "StationInfo")
        self.assertEqual(
            kwargs["json"]["travelDate"],
            datetime.now(tz).strftime("%Y-%m-%dT00:00:00"),
        )
        self.assertEqual(kwargs["json"]["maxCount"], "500")
        self.assertEqual(kwargs["headers"], ELVIRA_HEADERS)

    async def test_non_success_response_returns_empty_station_data(self):
        response = MagicMock()
        response.status = 503

        class ResponseContext:
            async def __aenter__(self):
                return response

            async def __aexit__(self, *args):
                return None

        session = MagicMock()
        session.post.return_value = ResponseContext()

        with patch("custom_components.bkk_stop.elvira._LOGGER.warning"):
            self.assertEqual(
                await _fetch_station(session, "008001000", timezone.utc), ([], [])
            )


if __name__ == "__main__":
    unittest.main()
