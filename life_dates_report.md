# Life dates: HLS and Wikidata against the register

Written by `check_life_dates.py`. 309 register persons are linked to 250 HLS biographies; the table behind this report is `life_dates_check.csv`, the persons that were split are in `hls_life_splits.csv`. The rules are those of `lifedates.py`.

## The two sources

**Birth** — 176 × the two sources agree; 61 × no year-precise date on Wikidata; 6 × HLS gives a fence (first mention, before, after); Wikidata's year is taken; 4 × Wikidata repeats the HLS's first or last mention as the date; 3 × Wikidata's year does not respect the HLS fence and is ignored.

**Death** — 189 × the two sources agree; 42 × no year-precise date on Wikidata; 11 × HLS gives a fence (first mention, before, after); Wikidata's year is taken; 4 × Wikidata's year does not respect the HLS fence and is ignored; 4 × two firm dates that differ — the life holds both.

Qualifiers of the HLS birth dates: exact 147, first mention 41, circa 32, before 16, range 13, after 1; of the death dates: exact 204, before 15, range 10, circa 8, after 7, last mention 6.

### Where HLS and Wikidata contradict each other (10)

| biography | HLS | Wikidata | what was done | life used |
|---|---|---|---|---|
| Adelberg Meyer zum Pfeil | birth 1482 (after) | 1474 | Wikidata's year does not respect the HLS fence and is ignored | born 1482–1502 |
| Caspar Angelroth | death 1535 (after) | 1511 | Wikidata's year does not respect the HLS fence and is ignored | died 1535–1575 |
| Diebold Ryff | death 1586 (exact) | 1547 | two firm dates that differ — the life holds both | died 1547–1586 |
| Hans Dürr | death 1528 (last mention) | 1511 | Wikidata's year does not respect the HLS fence and is ignored | died 1528–1568 |
| Hans Fries | death 1523 (last mention) | 1520 | Wikidata's year does not respect the HLS fence and is ignored | died 1523–1563 |
| Hartmann Münch von Münchenstein | birth 1368 (first mention) | 1386 | Wikidata's year does not respect the HLS fence and is ignored | born 1298–1354 |
| Henman Offenburg | death 1459 (exact) | 1454 | two firm dates that differ — the life holds both | died 1454–1459 |
| Johann Puliant von Eptingen | death 1399 (exact) | 1402 | two firm dates that differ — the life holds both | died 1399–1402 |
| Johannes Kolross | death 1558 (exact) | 1560 | two firm dates that differ — the life holds both | died 1558–1560 |
| Michael Wenssler | birth 1462 (first mention) | 1472 | Wikidata's year does not respect the HLS fence and is ignored | born 1392–1448 |
| Michael Wenssler | death 1499 (last mention) | 1497 | Wikidata's year does not respect the HLS fence and is ignored | died 1499–1539 |

## Register persons against the life

Every linked person fits the life of its biography: **yes**.

On the way there 141 persons of the raw index were taken apart, because part of their mentions lie outside the life — an earlier bearer of the name was split off 83 times, a later one 61 times. What the life excluded (persons):

- mentioned before the birth: 44
- a party to a transaction after the death: 39
- named as living more than 15 years after the death: 33
- called deceased before the death: 28
- a party to a transaction as a child: 19
- mentioned more than 60 years after the death: 4

| register person | mentions | biography | life (born … died) | kept | earlier bearer | later bearer |
|---|---|---|---|---|---|---|
| Adalberg Meyer | 1521–1601 ×11 | Adelberg Meyer zum Pfeil | 1482–1502 … 1548–1548 | 1521–1526 ×7 | – | 1591–1601 ×4 |
| Andreas Bischoff | 1473–1508 ×2 | Andreas Bischoff | 1481–1481 … 1558–1558 | 1508–1508 ×1 | 1473–1473 ×1 | – |
| Andres Bischoff | 1468–1542 ×7 | Andreas Bischoff | 1481–1481 … 1558–1558 | 1497–1542 ×6 | 1468–1468 ×1 | – |
| Andress Bischoffs | 1486–1488 ×2 | Andreas Bischoff | 1481–1481 … 1558–1558 | 1486–1486 ×1 | 1488–1488 ×1 | – |
| Andreas Burckhardts | 1653–1681 ×7 | Andreas Burckhardt | 1604–1604 … 1667–1667 | 1667–1681 ×6 | 1653–1653 ×1 | – |
| Andres Ryff | 1574–1638 ×10 | Andreas Ryff | 1550–1550 … 1603–1603 | 1574–1590 ×6 | – | 1621–1638 ×4 |
| anthoni Glasers | 1538–1575 ×4 | Antoni Glaser | 1477–1495 … 1550–1552 | 1538–1543 ×2 | – | 1559–1575 ×2 |
| Benedict Socin | 1632–1673 ×16 | Benedikt Socin | 1594–1594 … 1664–1664 | 1632–1673 ×15 | 1659–1659 ×1 | – |
| Bernhardt Brandt | 1557–1628 ×2 | Bernhard Brand | 1525–1525 … 1594–1594 | 1557–1557 ×1 | – | 1628–1628 ×1 |
| Blasin , Schöllin | 1559–1577 ×5 | Bläsi Schölli | 1448–1504 … 1569–1569 | 1559–1566 ×2 | – | 1571–1577 ×3 |
| Caspar Bauhin | 1614–1664 ×8 | Caspar Bauhin | 1560–1560 … 1624–1624 | 1614–1614 ×1 | – | 1629–1664 ×7 |
| Caspar Bauhinus | 1608–1672 ×4 | Caspar Bauhin | 1560–1560 … 1624–1624 | 1608–1617 ×2 | – | 1631–1672 ×2 |
| Caspar , Krug | 1559–1630 ×3 | Caspar Krug | 1518–1518 … 1579–1579 | 1559–1559 ×2 | – | 1630–1630 ×1 |
| Christian Wurstisen | 1582–1604 ×2 | Christian Wurstisen | 1544–1544 … 1588–1588 | 1604–1604 ×1 | 1582–1582 ×1 | – |
| Christian Wurstysen | 1582–1614 ×9 | Christian Wurstisen | 1544–1544 … 1588–1588 | 1582–1614 ×6 | 1582–1582 ×3 | – |
| Christof Burckhardts | 1679–1697 ×3 | Christoph Burckhardt | 1631–1631 … 1705–1705 | 1679–1679 ×1 | 1697–1697 ×2 | – |
| Christoff Burckhardt | 1617–1693 ×6 | Christoph Burckhardt | 1631–1631 … 1705–1705 | 1680–1693 ×3 | 1617–1625 ×3 | – |
| Christoph Burckhardt | 1616–1650 ×4 | Christoph Burckhardt | 1631–1631 … 1705–1705 | 1650–1650 ×2 | 1616–1630 ×2 | – |
| Christoph Burckhardts | 1642–1650 ×2 | Christoph Burckhardt | 1631–1631 … 1705–1705 | 1642–1642 ×1 | 1650–1650 ×1 | – |
| Christoph Burckhardts | 1647–1647 ×2 | Christoph Burckhardt | 1631–1631 … 1705–1705 | 1647–1647 ×1 | 1647–1647 ×1 | – |
| Emanuel König | 1657–1683 ×2 | Emanuel König | 1658–1658 … 1731–1731 | 1683–1683 ×1 | 1657–1657 ×1 | – |
| Emanuel König | 1673–1684 ×2 | Emanuel König | 1658–1658 … 1731–1731 | 1673–1673 ×1 | 1684–1684 ×1 | – |
| Emanuel Ryhiner | 1574–1630 ×12 | Emanuel Ryhiner | 1543–1543 … 1582–1582 | 1574–1580 ×5 | – | 1587–1630 ×7 |
| Emanuel Socin | 1602–1680 ×11 | Emanuel Socin | 1628–1628 … 1717–1717 | 1662–1680 ×8 | 1602–1633 ×3 | – |
| Emanuel Socins | 1603–1680 ×4 | Emanuel Socin | 1628–1628 … 1717–1717 | 1680–1680 ×1 | 1603–1637 ×3 | – |
| Eucharins Holtzach | 1501–1538 ×7 | Eucharius Holzach | 1475–1485 … 1521–1521 | 1501–1519 ×5 | – | 1538–1538 ×2 |
| Felix Platters | 1599–1675 ×4 | Felix Platter | 1536–1536 … 1614–1614 | 1599–1610 ×3 | – | 1675–1675 ×1 |
| Frantz Brunschweiler | 1605–1659 ×16 | Franz Robert Brunschweiler | 1635–1635 … 1690–1690 | 1651–1659 ×5 | 1605–1638 ×11 | – |
| Frantz Brunschweilern | 1633–1664 ×3 | Franz Robert Brunschweiler | 1635–1635 … 1690–1690 | 1664–1664 ×1 | 1633–1636 ×2 | – |
| Fridlin , Ryff | 1531–1587 ×4 | Fridolin Ryff | 1483–1493 … 1554–1554 | 1531–1535 ×3 | – | 1587–1587 ×1 |
| Gregorio Brandmüllern | 1669–1676 ×6 | Gregor Brandmüller | 1661–1661 … 1691–1691 | 1676–1676 ×1 | 1669–1672 ×5 | – |
| Gregorius Brandmüller | 1646–1680 ×4 | Gregor Brandmüller | 1661–1661 … 1691–1691 | 1678–1680 ×2 | 1646–1672 ×2 | – |
| Gedeon Sarasin | 1628–1686 ×7 | Gédéon Sarasin | 1573–1573 … 1636–1636 | 1628–1630 ×2 | – | 1685–1686 ×5 |
| Hansen Bart | 1449–1505 ×2 | Hans Bär | 1454–1484 … 1515–1515 | 1505–1505 ×1 | 1449–1449 ×1 | – |
| Joh . de Bary | 1449–1512 ×3 | Hans Bär | 1454–1484 … 1515–1515 | 1486–1512 ×2 | 1449–1449 ×1 | – |
| Hanns Franck | 1468–1537 ×9 | Hans Franck | 1480–1490 … 1522–1522 | 1510–1537 ×8 | 1468–1468 ×1 | – |
| Hanns Frank | 1503–1541 ×2 | Hans Franck | 1480–1490 … 1522–1522 | 1503–1503 ×1 | – | 1541–1541 ×1 |
| Hans von Friesen | 1440–1500 ×4 | Hans Fries | 1460–1470 … 1523–1563 | 1500–1500 ×1 | 1440–1440 ×3 | – |
| Hanns Gallician | 1480–1531 ×5 | Hans Gallizian | 1472–1472 … 1524–1524 | 1501–1531 ×4 | 1480–1480 ×1 | – |
| Johannes Gysin | 1664–1699 ×10 | Hans Gysin | 1611–1611 … 1664–1674 | 1664–1668 ×3 | – | 1678–1699 ×7 |
| Hans Herbst | 1457–1510 ×4 | Hans Herbst | 1470–1470 … 1552–1552 | 1509–1510 ×3 | 1457–1457 ×1 | – |
| Hanns Gilgenberg | 1451–1481 ×17 | Hans Imer von Gilgenberg | 1439–1469 … 1533–1533 | 1463–1481 ×12 | 1451–1451 ×5 | – |
| Johann Jacob Zörnlin | 1657–1662 ×2 | Hans Jakob Zörnlin | 1588–1588 … 1659–1659 | 1662–1662 ×1 | 1657–1657 ×1 | – |
| Hanns Mentzinger | 1457–1525 ×5 | Hans Mentzinger | 1492–1492 … 1540–1550 | 1519–1525 ×3 | 1457–1477 ×2 | – |
| Hans Muntzinger | 1462–1521 ×8 | Hans Mentzinger | 1492–1492 … 1540–1550 | 1507–1521 ×2 | 1462–1500 ×6 | – |
| Hans Muntzinger | 1540–1590 ×2 | Hans Mentzinger | 1492–1492 … 1540–1550 | 1540–1540 ×1 | – | 1590–1590 ×1 |
| Hansen Muntzinger | 1462–1528 ×3 | Hans Mentzinger | 1492–1492 … 1540–1550 | 1528–1528 ×2 | 1462–1462 ×1 | – |
| Hansen Muntzingers | 1474–1509 ×3 | Hans Mentzinger | 1492–1492 … 1540–1550 | 1509–1509 ×1 | 1474–1483 ×2 | – |
| Hanns Sperrer | 1457–1517 ×14 | Hans Sperrer | 1429–1429 … 1451–1461 | 1457–1457 ×1 | – | 1463–1517 ×13 |
| Hanns Sürlin | 1434–1491 ×12 | Hans Sürlin | 1324–1380 … 1455–1455 | 1434–1454 ×4 | – | 1482–1491 ×8 |
| Hans Sürlin | 1421–1491 ×9 | Hans Sürlin | 1324–1380 … 1455–1455 | 1421–1439 ×6 | – | 1485–1491 ×3 |
| Hanns Zschekaburlin | 1455–1485 ×19 | Hans Zscheckenbürlin | 1338–1394 … 1477–1477 | 1455–1474 ×12 | – | 1479–1485 ×7 |
| Hanns von Flachslanden | 1414–1451 ×2 | Hans von Flachslanden | 1412–1412 … 1476–1476 | 1451–1451 ×1 | 1414–1414 ×1 | – |
| Hans von Flachsland | 1437–1507 ×2 | Hans von Flachslanden | 1412–1412 … 1476–1476 | 1437–1437 ×1 | – | 1507–1507 ×1 |
| Hansen von Flachslanden | 1449–1498 ×4 | Hans von Flachslanden | 1412–1412 … 1476–1476 | 1449–1469 ×3 | – | 1498–1498 ×1 |
| Heinrich Halbysen | 1448–1472 ×4 | Heinrich Halbisen | 1385–1395 … 1450–1452 | 1448–1448 ×2 | – | 1455–1472 ×2 |
| Heinrich Halbysen | 1451–1470 ×2 | Heinrich Halbisen | 1385–1395 … 1450–1452 | 1451–1451 ×1 | – | 1470–1470 ×1 |
| Heinrich Meltinger | 1500–1526 ×13 | Heinrich Meltinger | 1441–1471 … 1531–1531 | 1500–1526 ×12 | 1526–1526 ×1 | – |
| Heinrich Meltingers | 1510–1529 ×16 | Heinrich Meltinger | 1441–1471 … 1531–1531 | 1510–1528 ×15 | 1529–1529 ×1 | – |
| Heinrich Zeiglers | 1460–1490 ×4 | Heinrich Zeigler | 1405–1415 … 1476–1486 | 1489–1490 ×3 | 1460–1460 ×1 | – |
| Heman Offenburg | 1429–1502 ×2 | Henman Offenburg | 1379–1379 … 1454–1459 | 1429–1429 ×1 | – | 1502–1502 ×1 |
| Henman Offenbergs | 1448–1525 ×2 | Henman Offenburg | 1379–1379 … 1454–1459 | 1448–1448 ×1 | – | 1525–1525 ×1 |
| Henman v . Offenburg | 1405–1405 ×2 | Henman Offenburg | 1379–1379 … 1454–1459 | 1405–1405 ×1 | 1405–1405 ×1 | – |
| Hieronymo Burckhardt | 1643–1695 ×6 | Hieronymus Burckhardt | 1680–1680 … 1737–1737 | 1695–1695 ×1 | 1643–1674 ×5 | – |
| Hieronymus Burckhardt | 1676–1699 ×2 | Hieronymus Burckhardt | 1680–1680 … 1737–1737 | 1699–1699 ×1 | 1676–1676 ×1 | – |
| Jacob Bertsche | 1631–1696 ×9 | Jacob Bertsche | 1635–1635 … 1707–1707 | 1679–1696 ×8 | 1631–1631 ×1 | – |
| Jacob Meyer | 1415–1492 ×3 | Jakob Meyer zum Hirzen | 1473–1473 … 1541–1541 | 1492–1492 ×1 | 1415–1447 ×2 | – |
| Jacob Meyger | 1540–1549 ×5 | Jakob Meyer zum Hirzen | 1473–1473 … 1541–1541 | 1540–1540 ×3 | – | 1546–1549 ×2 |
| Jacob Rudin | 1508–1569 ×4 | Jakob Rüdin | 1496–1506 … 1573–1573 | 1529–1569 ×2 | 1508–1569 ×2 | – |
| Jacob Rüedin | 1549–1628 ×8 | Jakob Rüdin | 1496–1506 … 1573–1573 | 1549–1549 ×1 | – | 1597–1628 ×7 |
| Hanns Heinrich Glaser | 1629–1675 ×8 | Johann Heinrich Glaser | 1629–1629 … 1675–1675 | 1643–1675 ×7 | 1629–1629 ×1 | – |
| Hanns Keller | 1621–1659 ×4 | Johann Heinrich Keller | 1627–1627 … 1708–1708 | 1642–1659 ×2 | 1621–1624 ×2 | – |
| Johannes Stähelin | 1663–1697 ×3 | Johann Heinrich Stähelin | 1668–1668 … 1721–1721 | 1697–1697 ×2 | 1663–1663 ×1 | – |
| Hanns Jacob Burckhardt | 1627–1691 ×10 | Johann Jakob Burckhardt | 1614–1614 … 1690–1690 | 1649–1691 ×9 | 1627–1627 ×1 | – |
| Johann Jacob Burckhardt | 1667–1697 ×5 | Johann Jakob Burckhardt | 1614–1614 … 1690–1690 | 1667–1667 ×1 | – | 1696–1697 ×4 |
| Hannss Merian | 1600–1669 ×6 | Johann Jakob Merian | 1648–1648 … 1724–1724 | 1669–1669 ×1 | 1600–1650 ×5 | – |
| Hanns Gengenbach | 1458–1499 ×9 | Johann Mathias Gengenbach | 1395–1451 … 1486–1486 | 1458–1477 ×4 | – | 1489–1499 ×5 |
| Hans von Gengenbach | 1482–1498 ×2 | Johann Mathias Gengenbach | 1395–1451 … 1486–1486 | 1482–1482 ×1 | – | 1498–1498 ×1 |
| Hanns Rudolf Burckhard | 1668–1698 ×3 | Johann Rudolf Burckhardt | 1620–1620 … 1683–1683 | 1668–1668 ×1 | – | 1693–1698 ×2 |
| Hanns Rudolff Burckhardt | 1606–1686 ×16 | Johann Rudolf Burckhardt | 1620–1620 … 1683–1683 | 1652–1683 ×12 | 1606–1606 ×1 | 1686–1686 ×3 |
| Hanns Rudolph Burckhardt | 1649–1692 ×10 | Johann Rudolf Burckhardt | 1620–1620 … 1683–1683 | 1649–1672 ×8 | – | 1692–1692 ×2 |
| Hanns Rudolph Burckhart | 1610–1663 ×3 | Johann Rudolf Burckhardt | 1620–1620 … 1683–1683 | 1663–1663 ×1 | 1610–1619 ×2 | – |
| Hans Rudolph Burckhardt | 1643–1692 ×4 | Johann Rudolf Burckhardt | 1620–1620 … 1683–1683 | 1643–1645 ×2 | – | 1692–1692 ×2 |
| Hans Rudolph Burckhart | 1585–1663 ×2 | Johann Rudolf Burckhardt | 1620–1620 … 1683–1683 | 1663–1663 ×1 | 1585–1585 ×1 | – |
| Johann Rudolf Burckhardts | 1680–1693 ×3 | Johann Rudolf Burckhardt | 1620–1620 … 1683–1683 | 1685–1693 ×2 | 1680–1680 ×1 | – |
| Johann Rudolff Burckhardt | 1632–1693 ×15 | Johann Rudolf Burckhardt | 1620–1620 … 1683–1683 | 1657–1680 ×10 | 1632–1632 ×3 | 1691–1693 ×2 |
| Johann Rudolph Burckhardt | 1621–1675 ×7 | Johann Rudolf Burckhardt | 1620–1620 … 1683–1683 | 1656–1675 ×4 | 1621–1625 ×3 | – |
| Hanns Rudolf Faesch | 1610–1690 ×11 | Johann Rudolf Faesch | 1644–1644 … 1709–1709 | 1676–1690 ×9 | 1610–1628 ×2 | – |
| Hanns Ringler | 1567–1600 ×4 | Johann Wernhard Ringler | 1570–1570 … 1630–1630 | 1600–1600 ×1 | 1567–1576 ×3 | – |
| Hansen von Sennhein | 1423–1441 ×3 | Johann von Sennheim | 1284–1340 … 1404–1435 | 1423–1424 ×2 | – | 1441–1441 ×1 |
| Johann Brandmüller | 1568–1647 ×15 | Johannes Brandmüller | 1593–1593 … 1664–1664 | 1613–1647 ×14 | 1568–1568 ×1 | – |
| Johann Brandmüller | 1646–1695 ×3 | Johannes Brandmüller | 1593–1593 … 1664–1664 | 1646–1646 ×1 | – | 1678–1695 ×2 |
| Johann Brandtmüller | 1618–1662 ×4 | Johannes Brandmüller | 1593–1593 … 1664–1664 | 1618–1631 ×2 | 1652–1662 ×2 | – |
| Johannes Brandmüller | 1623–1691 ×10 | Johannes Brandmüller | 1593–1593 … 1664–1664 | 1623–1664 ×6 | – | 1680–1691 ×4 |
| Hans Froben | 1506–1522 ×5 | Johannes Froben | 1455–1465 … 1527–1527 | 1506–1522 ×4 | 1522–1522 ×1 | – |
| Johannes Kutzer | 1400–1435 ×2 | Johannes Kreutzer | 1419–1429 … 1468–1468 | 1435–1435 ×1 | 1400–1400 ×1 | – |
| Hans Mürern | 1523–1544 ×3 | Johannes Murer | 1400–1456 … 1529–1531 | 1523–1523 ×1 | – | 1533–1544 ×2 |
| Hanns Miller | 1581–1661 ×6 | Johannes Müller | 1599–1655 … 1691–1691 | 1649–1661 ×2 | 1581–1601 ×4 | – |
| Hanns Müller | 1581–1653 ×7 | Johannes Müller | 1599–1655 … 1691–1691 | 1647–1653 ×2 | 1581–1594 ×5 | – |
| Hans Müllers | 1640–1653 ×5 | Johannes Müller | 1599–1655 … 1691–1691 | 1640–1644 ×2 | 1645–1653 ×3 | – |
| Johann Mülleren | 1629–1661 ×3 | Johannes Müller | 1599–1655 … 1691–1691 | 1629–1634 ×2 | 1661–1661 ×1 | – |
| Johann Müllern | 1625–1655 ×3 | Johannes Müller | 1599–1655 … 1691–1691 | 1625–1655 ×2 | 1655–1655 ×1 | – |
| Johann Müllers | 1623–1691 ×8 | Johannes Müller | 1599–1655 … 1691–1691 | 1623–1691 ×3 | 1669–1672 ×5 | – |
| Johannes Müller | 1640–1690 ×5 | Johannes Müller | 1599–1655 … 1691–1691 | 1640–1690 ×4 | 1668–1668 ×1 | – |
| Johannes Müllers | 1661–1700 ×7 | Johannes Müller | 1599–1655 … 1691–1691 | 1661–1692 ×2 | – | 1693–1700 ×5 |
| Hans Scherer | 1459–1526 ×7 | Johannes Scherrer | 1335–1391 … 1421–1461 | 1459–1459 ×1 | – | 1478–1526 ×6 |
| Hans Scherrer | 1459–1479 ×2 | Johannes Scherrer | 1335–1391 … 1421–1461 | 1459–1459 ×1 | – | 1479–1479 ×1 |
| Johannes Tschudz | 1680–1692 ×2 | Johannes Tschudy | 1672–1672 … 1736–1736 | 1680–1680 ×1 | 1692–1692 ×1 | – |
| Johann Wolleben | 1626–1671 ×3 | Johannes Wolleb | 1586–1586 … 1629–1629 | 1626–1626 ×2 | – | 1671–1671 ×1 |
| Hanns von Berenfels | 1456–1496 ×22 | Johannes von Bärenfels | 1451–1451 … 1494–1496 | 1466–1496 ×18 | 1456–1463 ×4 | – |
| Hans von Berenfels | 1428–1482 ×6 | Johannes von Bärenfels | 1451–1451 … 1494–1496 | 1470–1482 ×2 | 1428–1463 ×4 | – |
| Martin Lebzelter | 1512–1565 ×2 | Martin Lebzelter | 1422–1478 … 1520–1520 | 1512–1512 ×1 | – | 1565–1565 ×1 |
| Martin Letzelter | 1493–1558 ×5 | Martin Lebzelter | 1422–1478 … 1520–1520 | 1493–1493 ×4 | – | 1558–1558 ×1 |
| Michel Glasers | 1456–1464 ×4 | Michel Glaser | 1365–1421 … 1474–1514 | 1456–1457 ×3 | 1464–1464 ×1 | – |
| Nicolai Passavant | 1623–1679 ×3 | Nicolas Passavant | 1559–1559 … 1633–1633 | 1623–1623 ×1 | – | 1679–1679 ×2 |
| Claus Murer | 1407–1469 ×10 | Niklaus Murer | 1334–1390 … 1433–1433 | 1407–1426 ×4 | – | 1456–1469 ×6 |
| Claus Mürer | 1408–1483 ×27 | Niklaus Murer | 1334–1390 … 1433–1433 | 1408–1434 ×12 | – | 1449–1483 ×15 |
| Niclaus Gürtlern | 1657–1669 ×3 | Nikolaus Gürtler | 1654–1654 … 1711–1711 | 1669–1669 ×1 | 1657–1658 ×2 | – |
| Niclaus Harscher | 1647–1700 ×15 | Nikolaus Harscher | 1683–1683 … 1742–1742 | 1700–1700 ×1 | 1647–1692 ×14 | – |
| Niclaus Rippel | 1590–1644 ×14 | Nikolaus Rippel | 1594–1594 … 1666–1666 | 1608–1644 ×5 | 1590–1605 ×9 | – |
| Peter , Offenburg | 1405–1479 ×15 | Peter Offenburg | 1458–1458 … 1514–1514 | 1474–1479 ×3 | 1405–1471 ×12 | – |
| Peter Offenburg | 1442–1500 ×3 | Peter Offenburg | 1458–1458 … 1514–1514 | 1500–1500 ×1 | 1442–1463 ×2 | – |
| Peter Offenburgs | 1463–1474 ×7 | Peter Offenburg | 1458–1458 … 1514–1514 | 1474–1474 ×1 | 1463–1474 ×6 | – |
| Peter Roth | 1461–1535 ×4 | Peter Rot | 1382–1438 … 1487–1487 | 1461–1465 ×2 | – | 1535–1535 ×2 |
| Renigins Faesch | 1659–1692 ×2 | Remigius Faesch | 1595–1595 … 1667–1667 | 1659–1659 ×1 | – | 1692–1692 ×1 |
| Salome Burckhardtin | 1650–1696 ×6 | Salome Schönauer | 1640–1640 … 1691–1691 | 1666–1675 ×4 | 1650–1650 ×1 | 1696–1696 ×1 |
| Samuel Braun | 1627–1695 ×11 | Samuel Braun | 1590–1590 … 1668–1668 | 1627–1667 ×4 | – | 1680–1695 ×7 |
| Samuel Braunen | 1587–1610 ×4 | Samuel Braun | 1590–1590 … 1668–1668 | 1610–1610 ×3 | 1587–1587 ×1 | – |
| Sebastian Beck | 1610–1680 ×3 | Sebastian Beck | 1583–1583 … 1654–1654 | 1610–1626 ×2 | – | 1680–1680 ×1 |
| Sebastian Beckh | 1579–1624 ×7 | Sebastian Beck | 1583–1583 … 1654–1654 | 1605–1610 ×2 | 1579–1624 ×5 | – |
| Sebastian Faeschen | 1640–1694 ×2 | Sebastian Faesch | 1647–1647 … 1712–1712 | 1694–1694 ×1 | 1640–1640 ×1 | – |
| Sebastean Spörlin | 1587–1662 ×6 | Sebastian Spörlin | 1560–1560 … 1644–1644 | 1587–1592 ×4 | – | 1662–1662 ×2 |
| Sebastian Spörlin | 1581–1654 ×23 | Sebastian Spörlin | 1560–1560 … 1644–1644 | 1581–1645 ×20 | – | 1646–1654 ×3 |
| Simon Battieren | 1631–1663 ×4 | Simon Battier | 1629–1629 … 1681–1681 | 1631–1652 ×3 | 1663–1663 ×1 | – |
| Ullrich Hugwaldt | 1558–1590 ×2 | Ulrich Hugwald | 1496–1496 … 1571–1571 | 1558–1558 ×1 | – | 1590–1590 ×1 |
| Ulrich Schultheiss | 1556–1633 ×7 | Ulrich Schultheiss | 1533–1533 … 1599–1599 | 1556–1573 ×6 | – | 1633–1633 ×1 |
| Ulrich Schulthes | 1526–1574 ×2 | Ulrich Schultheiss | 1533–1533 … 1599–1599 | 1574–1574 ×1 | 1526–1526 ×1 | – |
| Ulrich Schulthess | 1539–1587 ×6 | Ulrich Schultheiss | 1533–1533 … 1599–1599 | 1577–1587 ×2 | 1539–1540 ×4 | – |
| Werner Wölfflin | 1501–1510 ×2 | Werner Wölfflin | 1374–1430 … 1494–1504 | 1501–1501 ×1 | – | 1510–1510 ×1 |
| Wernher Wolfflin | 1463–1509 ×4 | Werner Wölfflin | 1374–1430 … 1494–1504 | 1463–1490 ×3 | – | 1509–1509 ×1 |
| Wernher Wölfflin | 1501–1572 ×2 | Werner Wölfflin | 1374–1430 … 1494–1504 | 1501–1501 ×1 | – | 1572–1572 ×1 |

