using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Safari
{
    public abstract class Animal
    {
        // annimal has its attributes field, and the counter + mutex is used to determine uniqe id. 
        private static int counter = 1;
        private static Mutex mutex = new Mutex();

        private double arrival_time;
        private double drink_time;
        private String type;
        private int id;

        public Animal(double arrival_time, double drink_time, string type)
        {
            this.arrival_time = arrival_time;
            this.drink_time = drink_time;
            this.type = type;

            // we lock the mutex for the id sumbission and update
            mutex.WaitOne();
            this.id = counter++;
            mutex.ReleaseMutex();
        }

        public String get_type()
        {
            return type;
        }

        public double get_drinking_time()
        {
            return drink_time;
        }

        public double get_arrival_time()
        {
            return arrival_time;
        }

        public int getID() {
            return id;
        }
    }
}
