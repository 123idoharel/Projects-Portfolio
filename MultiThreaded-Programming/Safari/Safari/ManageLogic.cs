using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Text;
using System.Threading.Tasks;
using Safari;

namespace Safari
{ 
    // the class manages the safari in terms of holding the 3 lakes, form, and a semaphore used to control the threads creation. 
    internal class ManageLogic
    {
        private Form1 form;
        private Lake lakeA;
        private Lake lakeB;
        private Lake lakeC;
        private static Random random = new Random();
        private SemaphoreSlim semaphore = new SemaphoreSlim(100);


        // constructor
        public ManageLogic(Form1 f)
        {
            this.form = f;
            this.lakeA = new Lake(5, "A", f.panel1);
            this.lakeB = new Lake(7, "B", f.panel2);
            this.lakeC = new Lake(10, "C", f.panel3);

        }

        // generates endlessly animals and submitts each animal to a thread who manages its behavior in the safari.
        // the animal and lake are random.
        // runs in a new background thread - in order to not stuck the main thread.  
        public void start()
        {
            Thread generator = new Thread(() =>
            {
                while (true)
                {
                    semaphore.Wait(); 
                    Animal a = createRandomAnimal();
                    Lake l = chooseRandomLake();

                    Thread t = new Thread(() =>
                    {
                        try
                        {
                            doWork(a, l);
                        }
                        finally
                        {
                            semaphore.Release();
                        }
                    });
                    t.Start();
                }
            });

            generator.IsBackground = true;
            generator.Start();
        }

        // creates a randon animal
        public Animal createRandomAnimal()
        {
            int chosen = random.Next(0, 3);
            if (chosen == 0)
            {
                return new Flamingo();
            }
            else if (chosen == 1) { 
                return new Zebra();
            }
            else{
                return new Hippopotamus();
            }
        }

        // chooses a random lake
        public Lake chooseRandomLake()
        {
            int chosen = random.Next(0, 3);
            if (chosen == 0)
            {
                return this.lakeA;
            }
            else if (chosen == 1) { 
                return this.lakeB;
            }
            else
            {
                return this.lakeC;
            }
        }

        // the doWork function refers to the letAnimalDrink in Lake class
        public void doWork(Animal animal, Lake lake)
        {
            lake.letAnimalDrink(animal, form);
        }
    }
    
}
