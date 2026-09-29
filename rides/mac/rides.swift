// family-rides: turns the ride definitions in rides.json into standalone
// calendar events on the Unassigned calendar, a rolling window ahead.
//
// Standalone, not recurring, because Apple Calendar can only move a whole
// series between calendars. A standalone ride is assigned with right-click ->
// Calendar -> a parent.
//
//   family-rides --config rides.json --dry-run    show what would be created
//   family-rides --config rides.json              create
//   family-rides --config rides.json --purge "School AM"
//                     delete future, still-unassigned rides of that title
//
// A ledger remembers every ride ever created, so a ride that was moved or
// deleted by hand is never recreated.

import EventKit
import Foundation

struct Times: Codable { let start: String; let end: String }

struct Series: Codable {
    let title: String
    let days: [String]
    let start: String
    let end: String
    let from: String?
    let until: String?
    let school_days_only: Bool?
    let early_release: Times?
}

struct School: Codable {
    let calendars: [String]
    let no_school_keywords: [String]
    let early_release_keywords: [String]
}

struct Config: Codable {
    let target_calendar: String
    let assigned_calendars: [String]
    let horizon_days: Int
    let through: String?
    let holidays: [String]?
    let school: School?
    let series: [Series]
}

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write(Data("error: \(msg)\n".utf8))
    exit(1)
}

// MARK: arguments

var configPath: String?
var dryRun = false
var purgeTitle: String?
var args = Array(CommandLine.arguments.dropFirst())
while !args.isEmpty {
    let a = args.removeFirst()
    switch a {
    case "--config": configPath = args.isEmpty ? nil : args.removeFirst()
    case "--dry-run": dryRun = true
    case "--list-calendars": break
    case "--purge": purgeTitle = args.isEmpty ? nil : args.removeFirst()
    default: fail("unknown argument \(a)")
    }
}
guard let configPath else { fail("--config <path> is required") }

let config: Config
do {
    config = try JSONDecoder().decode(Config.self, from: Data(contentsOf: URL(fileURLWithPath: configPath)))
} catch {
    fail("cannot read \(configPath): \(error)")
}

// MARK: calendar access

let store = EKEventStore()
let sem = DispatchSemaphore(value: 0)
var granted = false
store.requestFullAccessToEvents { ok, _ in granted = ok; sem.signal() }
sem.wait()
guard granted else {
    fail("no calendar access. System Settings -> Privacy & Security -> Calendars -> family-rides: Full Access")
}

// iCloud names can carry curly apostrophes; compare with them straightened.
func norm(_ s: String) -> String {
    s.replacingOccurrences(of: "\u{2019}", with: "'").lowercased()
}

let allCalendars = store.calendars(for: .event)
if CommandLine.arguments.contains("--list-calendars") {
    for c in allCalendars.sorted(by: { $0.title < $1.title }) {
        print("\(c.allowsContentModifications ? "rw" : "ro")  \(c.source.title)  \"\(c.title)\"")
    }
    exit(0)
}
func calendar(named name: String, writable: Bool) -> EKCalendar {
    let hits = allCalendars.filter { norm($0.title) == norm(name) && (!writable || $0.allowsContentModifications) }
    if hits.isEmpty { fail("no\(writable ? " writable" : "") calendar named \"\(name)\"") }
    if hits.count > 1 { fail("\(hits.count) calendars named \"\(name)\", rename one") }
    return hits[0]
}

let target = calendar(named: config.target_calendar, writable: true)
let checkCalendars = [target] + config.assigned_calendars.map { calendar(named: $0, writable: true) }
let schoolCalendars = (config.school?.calendars ?? []).map { calendar(named: $0, writable: false) }

// MARK: ledger

let ledgerURL = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/family-rides/ledger.json")
var ledger: [String: String] = (try? JSONDecoder().decode([String: String].self, from: Data(contentsOf: ledgerURL))) ?? [:]

func saveLedger() {
    try? FileManager.default.createDirectory(at: ledgerURL.deletingLastPathComponent(), withIntermediateDirectories: true)
    let enc = JSONEncoder()
    enc.outputFormatting = [.prettyPrinted, .sortedKeys]
    do { try enc.encode(ledger).write(to: ledgerURL) } catch { fail("cannot write ledger: \(error)") }
}

// MARK: dates

let cal = Calendar.current
let dayFmt = DateFormatter()
dayFmt.calendar = cal
dayFmt.timeZone = cal.timeZone
dayFmt.dateFormat = "yyyy-MM-dd"
let weekdayNames = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

func at(_ day: Date, _ hhmm: String, _ title: String) -> Date {
    let p = hhmm.split(separator: ":").compactMap { Int($0) }
    guard p.count == 2, let d = cal.date(bySettingHour: p[0], minute: p[1], second: 0, of: day) else {
        fail("\(title): bad time \"\(hhmm)\", use HH:MM 24-hour")
    }
    return d
}

func parseDay(_ s: String, _ title: String) -> Date {
    guard let d = dayFmt.date(from: s) else { fail("\(title): bad date \"\(s)\", use YYYY-MM-DD") }
    return cal.startOfDay(for: d)
}

func key(_ title: String, _ day: Date) -> String { "\(title)|\(dayFmt.string(from: day))" }

let now = Date()
let today = cal.startOfDay(for: now)

// MARK: purge

if let purgeTitle {
    let end = cal.date(byAdding: .day, value: 400, to: today)!
    let pred = store.predicateForEvents(withStart: now, end: end, calendars: [target])
    var removed = 0
    for ev in store.events(matching: pred) where ev.title == purgeTitle && !ev.hasRecurrenceRules {
        let k = key(purgeTitle, cal.startOfDay(for: ev.startDate))
        guard ledger[k] != nil else { continue }
        print("\(dryRun ? "would delete" : "delete")  \(dayFmt.string(from: ev.startDate))  \(purgeTitle)")
        if !dryRun { try? store.remove(ev, span: .thisEvent, commit: false) }
        removed += 1
    }
    // Forget future entries so a changed definition regenerates. Rides already
    // moved to a parent are protected by the existence check instead.
    if !dryRun {
        for k in ledger.keys where k.hasPrefix("\(purgeTitle)|") {
            if let d = dayFmt.date(from: String(k.split(separator: "|").last ?? "")), d >= today {
                ledger.removeValue(forKey: k)
            }
        }
        do { try store.commit() } catch { fail("commit failed: \(error)") }
        saveLedger()
    }
    print("\(removed) ride(s) \(dryRun ? "would be " : "")deleted")
    exit(0)
}

// MARK: generate

func schoolFlags(_ day: Date) -> (noSchool: Bool, earlyRelease: Bool) {
    guard let school = config.school, !schoolCalendars.isEmpty else { return (false, false) }
    let pred = store.predicateForEvents(withStart: day, end: cal.date(byAdding: .day, value: 1, to: day)!, calendars: schoolCalendars)
    let titles = store.events(matching: pred).map { norm($0.title ?? "") }
    let has = { (words: [String]) in titles.contains { t in words.contains { t.contains(norm($0)) } } }
    return (has(school.no_school_keywords), has(school.early_release_keywords))
}

// The window is horizon_days ahead, or up to `through` if that is later.
var windowDays = config.horizon_days
if let t = config.through {
    let end = parseDay(t, "through")
    windowDays = max(windowDays, (cal.dateComponents([.day], from: today, to: end).day ?? 0) + 1)
}

var created = 0, skipped = 0
for offset in 0..<windowDays {
    let day = cal.date(byAdding: .day, value: offset, to: today)!
    let weekday = weekdayNames[cal.component(.weekday, from: day) - 1]
    let flags = schoolFlags(day)
    if (config.holidays ?? []).contains(dayFmt.string(from: day)) {
        if dryRun { print("holiday     \(weekday) \(dayFmt.string(from: day))  no rides") }
        continue
    }
    if dryRun && (flags.noSchool || flags.earlyRelease) && !["Sat", "Sun"].contains(weekday) {
        print("school      \(weekday) \(dayFmt.string(from: day))  \(flags.noSchool ? "NO SCHOOL" : "early release")")
    }

    for s in config.series where s.days.contains(weekday) {
        if let f = s.from, day < parseDay(f, s.title) { continue }
        if let u = s.until, day > parseDay(u, s.title) { continue }
        if s.school_days_only == true && flags.noSchool { continue }

        let times = (flags.earlyRelease ? s.early_release : nil) ?? Times(start: s.start, end: s.end)
        let start = at(day, times.start, s.title)
        let end = at(day, times.end, s.title)
        if start < now { continue }

        let k = key(s.title, day)
        if ledger[k] != nil { skipped += 1; continue }

        // Already there, on Unassigned or a parent (added by hand, or a first
        // run over rides that exist): adopt it rather than duplicate it.
        let dayPred = store.predicateForEvents(withStart: day, end: cal.date(byAdding: .day, value: 1, to: day)!, calendars: checkCalendars)
        if store.events(matching: dayPred).contains(where: { $0.title == s.title }) {
            if !dryRun { ledger[k] = "existing" }
            skipped += 1
            continue
        }

        let note = flags.earlyRelease && s.early_release != nil ? "  (early release)" : ""
        print("\(dryRun ? "would create" : "create")  \(weekday) \(dayFmt.string(from: day))  \(times.start)-\(times.end)  \(s.title)\(note)")
        created += 1
        if dryRun { continue }

        let ev = EKEvent(eventStore: store)
        ev.calendar = target
        ev.title = s.title
        ev.startDate = start
        ev.endDate = end
        do { try store.save(ev, span: .thisEvent, commit: false) } catch { fail("save \(k) failed: \(error)") }
        ledger[k] = ISO8601DateFormatter().string(from: now)
    }
}

if !dryRun {
    do { try store.commit() } catch { fail("commit failed: \(error)") }
    saveLedger()
}
print("\(created) \(dryRun ? "to create" : "created"), \(skipped) already handled, window \(dayFmt.string(from: today)) + \(windowDays) days")
