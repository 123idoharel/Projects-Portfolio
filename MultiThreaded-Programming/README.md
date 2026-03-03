# 🧵 Multithreaded Systems – Safari & SharableSpreadSheet

**Language:** C#  
**Technologies:** Threads, Semaphore, SemaphoreSlim, Mutex
**Topics:** Readers–Writers, Lock Striping, Deadlock Prevention  

This folder contains two major multithreaded systems:

1. Safari Simulation 
2. SharableSpreadSheet System – Thread-safe SharableSpreadsheet (A) + Simulator (B) + GUI-SpreadsheetApp (C) 

Both projects emphasize:
- Correct synchronization
- Fine-grained locking
- Deadlock avoidance
- 
---

# Safari Simulation

## 🎯 Goal:

Simulate animals (Hippo, Zebra, Flamingo) drinking from shared lakes concurrently while enforcing synchronization constraints.

Each animal:
- Runs in its own thread
- Requests access to a lake
- Waits if constraints are violated
- Drinks
- Releases resources

---

## 🧠 Synchronization Design:

### ✔ Thread Model
Each animal class (`Animal`, `Zebra`, `Hippopotamus`, `Flamingo`) runs on a dedicated thread.

### ✔ Lake Synchronization

Each `Lake` instance manages:

- `SemaphoreSlim` → limits number of animals drinking simultaneously
- `Mutex` → protects shared internal state (e.g., occupied positions array)
- Logical species-based constraints

Semaphore ensures bounded concurrency:
```
At most K animals drink simultaneously.
```

Mutex ensures:
```
Atomic updates to shared lake state.
```

---

### ✔ Deadlock Prevention

- Locks are acquired in consistent order
- No circular waiting
- Lake acts as single synchronization authority
- No nested conflicting lock acquisition

---


# 📊 – SharableSpreadSheet System

Includes:

- Thread-safe spreadsheet core (SharableSpreadSheet.cs)
- Multithreaded stress simulator (Simulator folder)
- GUI application (SpreadSheetApp folder)

---

# A – SharableSpreadSheet (Thread-Safe Core)

## 🎯 Goal

Implement a fully thread-safe spreadsheet supporting:

- getCell / setCell
- searchString / searchInRow / searchInCol / searchInRange
- exchangeRows / exchangeCols
- addRow / addCol
- findAll / setAll
- save / load

All under concurrent access.

---

## 🧠 Core Synchronization Strategy

### 1️⃣ Lock Striping (Chunk-Based Locking)

Instead of a single global lock:

```csharp
locksNum = Math.Min(Environment.ProcessorCount * 100, rows * cols);
```

Each cell is mapped to a lock chunk:

```csharp
int index = row * cols + col;
int mapped = (index * locksNum) / (rows * cols);
```

This enables:
- Parallel operations on different chunks
- Reduced contention
- Better scalability

---

### 2️⃣ Readers–Writers Pattern Per Chunk

Each chunk maintains:

- `SemaphoreSlim(1,1)` → Writers lock
- `Mutex` → Protects readers counter
- `int readersCount`

Reader algorithm:

1. Lock readers counter mutex  
2. Increment readersCount  
3. If first reader → acquire writers semaphore  
4. Unlock readers mutex  
5. Read  
6. Lock readers mutex  
7. Decrement readersCount  
8. If last reader → release writers semaphore  
9. Unlock readers mutex  

Writer algorithm:

1. Wait on writers semaphore  
2. Modify data  
3. Release writers semaphore  

---

### 3️⃣ Why SemaphoreSlim Instead of Mutex for Writers?

A `Mutex` must be released by the same thread that acquired it.

In readers–writers:
- First reader acquires writer lock
- Last reader releases writer lock
- These may be different threads

Therefore:
✔ `SemaphoreSlim(1,1)` is used.

---

### 4️⃣ Deadlock Prevention in Multi-Chunk Operations

For operations requiring multiple chunks:

- Collect chunk indices
- Insert into `HashSet`
- Convert to list
- Sort ascending
- Lock in sorted order

This guarantees:
✔ Deterministic lock ordering  
✔ No circular wait  
✔ No deadlocks  

---

### 5️⃣ Structural Modifications

Operations like:

- addRow
- addCol
- load
- save
- setAll

Lock ALL chunks as writers.

Reason:
- Matrix reference is replaced
- Dimensions change
- Global consistency required

---

### 6️⃣ Search Throttling

Optional search limit:

```csharp
Semaphore searchSemaphore;
```

If enabled:
- Limits number of concurrent search operations
- Prevents CPU overload under heavy search load

---

# B – Multithreaded Simulator

## 🎯 Goal

Stress-test the spreadsheet under heavy concurrent workload.

---

## 🧵 Execution Model

Parameters:
```
Simulator <rows> <cols> <threads> <operations> <sleep_ms>
```

Each thread:
- Performs random operations
- Sleeps between operations
- Logs activity

---

## ✔ Full API Coverage

Random operations include:

- getCell
- setCell
- searchString
- searchInRow
- searchInCol
- searchInRange
- exchangeRows
- exchangeCols
- addRow
- addCol
- findAll
- setAll
- getSize

---

## ✔ Design Principle

All synchronization responsibility lies inside `SharableSpreadSheet`.

---

# C – Spreadsheet GUI (SpreadSheetApp)

## 🎯 Goal

Provide graphical interface to the thread-safe spreadsheet.

---

## 🧱 Architecture

GUI contains:

- DataGridView
- Load button
- Save button
- Manual edit controls

Spreadsheet core handles all synchronization.

---

## 🔁 Grid Update Safety

To avoid recursive updates:

```csharp
private bool is_updating = false;
```

When rebuilding grid:
- Set `is_updating = true`
- Rebuild
- Set `is_updating = false`

Cell change handler:
```csharp
if (!is_updating)
    setCell(...)
```

Prevents event feedback loops.

---

## ✔ Load / Save

Load:
- Calls `SharableSpreadSheet.load()`
- Rebuilds grid

Save:
- Calls `SharableSpreadSheet.save()`

Synchronization handled internally by core.

---



# 📌 Final Note

Both Safari and SharableSpreadSheet systems are fully multithreaded, deadlock-safe, and designed with scalable fine-grained locking instead of simplistic global locking.

The projects demonstrate strong understanding of:
- Concurrency control
- Synchronization primitives
- Thread coordination
- Real-world multithreaded architecture
